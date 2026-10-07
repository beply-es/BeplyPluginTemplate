#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


EXCLUDED_ROOTS = {
    ".git",
    ".github",
    "Doc",
    "docs",
    "scripts",
    "Test",
    "Tests",
    "tests",
    "coverage-html",
    "playwright-report",
    "test-results",
}
EXCLUDED_NAMES = {
    "README.md",
    "CLAUDE.md",
    ".gitignore",
    "package.json",
    "package-lock.json",
    "playwright.config.ts",
    "run-tests.sh",
    "coverage.xml",
    "coverage-report.txt",
}
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
PLUGIN_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+$")
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
# Opt-in por repositorio: subdirectorios de scripts/ que el plugin necesita en producción. Sin el
# fichero todo scripts/ queda fuera, como siempre, así que no cambia nada para los demás plugins.
PACKAGE_POLICY = Path(".beply/package-policy.json")
SCRIPT_DIR_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
SUPPLY_CHAIN_LOCKS = (
    (Path("composer.lock"), Path(".beply/supply-chain/composer.lock")),
    (Path("package-lock.json"), Path(".beply/supply-chain/package-lock.json")),
    (Path("tests/package-lock.json"), Path(".beply/supply-chain/package-lock.json")),
)


class BuildError(RuntimeError):
    pass


def load_package_policy(plugin_root: Path) -> frozenset[str]:
    policy_path = plugin_root / PACKAGE_POLICY
    if policy_path.is_symlink():
        raise BuildError("symlinked package policy is forbidden")
    if not policy_path.exists():
        return frozenset()
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError("package policy is not valid JSON") from exc
    if not isinstance(policy, dict) or set(policy) != {"schema", "includeScripts"} or policy["schema"] != 1:
        raise BuildError("package policy must be {schema: 1, includeScripts: [...]}")
    include = policy["includeScripts"]
    if not isinstance(include, list) or not all(isinstance(item, str) and SCRIPT_DIR_RE.fullmatch(item) for item in include):
        raise BuildError("package policy includeScripts must list plain scripts/ subdirectory names")
    return frozenset(include)


def is_excluded(relative_path: Path, include_scripts: frozenset[str] = frozenset()) -> bool:
    if not relative_path.parts:
        return False
    if relative_path.name == ".env":
        return True
    if relative_path.name.startswith(".env") and relative_path.name != ".env.example":
        return True
    if relative_path.name in EXCLUDED_NAMES:
        return True
    if relative_path.parts[0] == "scripts" and len(relative_path.parts) > 2 and relative_path.parts[1] in include_scripts:
        return False
    return relative_path.parts[0] in EXCLUDED_ROOTS


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_plugin_zip(
    plugin_root: Path,
    output_path: Path,
    plugin_name: str,
    plugin_version: str,
) -> dict[str, Any]:
    plugin_root = plugin_root.resolve()
    output_path = output_path.resolve()
    if not plugin_root.is_dir():
        raise BuildError("plugin root is not a directory")
    if not PLUGIN_NAME_RE.fullmatch(plugin_name):
        raise BuildError("plugin name is not canonical")
    if not PLUGIN_VERSION_RE.fullmatch(plugin_version):
        raise BuildError("plugin version must use X.Y")
    if not (plugin_root / "facturascripts.ini").is_file():
        raise BuildError("facturascripts.ini is missing")

    include_scripts = load_package_policy(plugin_root)
    payload: list[tuple[Path, Path]] = []
    for path in sorted(plugin_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(plugin_root)
        if is_excluded(relative, include_scripts):
            continue
        if path.is_symlink():
            raise BuildError(f"symlinked payload entry is forbidden: {relative}")
        if not path.is_file():
            continue
        payload.append((relative, path))

    embedded_locks: dict[Path, Path] = {}
    for source_relative, archive_relative in SUPPLY_CHAIN_LOCKS:
        source = plugin_root / source_relative
        if source.is_symlink():
            raise BuildError(f"symlinked supply-chain lock is forbidden: {source_relative}")
        if source.is_file():
            embedded_locks.setdefault(archive_relative, source)
    payload = [(relative, path) for relative, path in payload if relative not in embedded_locks]
    payload.extend(sorted(embedded_locks.items(), key=lambda item: item[0].as_posix()))
    payload.sort(key=lambda item: item[0].as_posix())
    if not payload:
        raise BuildError("plugin payload is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, path in payload:
            archive_name = (Path(plugin_name) / relative).as_posix()
            info = ZipInfo(archive_name, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)

    result = {
        "artifactPath": str(output_path),
        "assetName": output_path.name,
        "checksum": sha256_file(output_path),
        "fileSize": output_path.stat().st_size,
        "pluginName": plugin_name,
        "version": plugin_version,
    }
    _append_github_output(
        {
            "artifact_path": result["artifactPath"],
            "asset_name": result["assetName"],
            "checksum": result["checksum"],
            "file_size": str(result["fileSize"]),
        }
    )
    return result


def _append_github_output(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one deterministic FacturaScripts plugin ZIP")
    parser.add_argument("--plugin-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plugin-name", required=True)
    parser.add_argument("--plugin-version", required=True)
    args = parser.parse_args()
    try:
        result = build_plugin_zip(
            args.plugin_root,
            args.output,
            args.plugin_name,
            args.plugin_version,
        )
    except BuildError as exc:
        parser.error(str(exc))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
