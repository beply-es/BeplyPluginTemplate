#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "beply.plugin.dev100.v1"
LOG_MARKER = "BEPLY_PLUGIN_DEV100_EVIDENCE_JSON="
IDENTITY_FIELDS = {
    "schemaVersion",
    "pluginName",
    "version",
    "versionId",
    "checksum",
    "fileSize",
    "releaseTag",
    "sourceSha",
}
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ContractError(RuntimeError):
    pass


def validate_immutable_identity(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != IDENTITY_FIELDS:
        raise ContractError("immutable identity fields do not match the canonical schema")
    identity = dict(raw)
    if identity.get("schemaVersion") != SCHEMA_VERSION:
        raise ContractError("immutable identity schema version is invalid")
    plugin_name = identity.get("pluginName")
    version = identity.get("version")
    version_id = identity.get("versionId")
    checksum = identity.get("checksum")
    file_size = identity.get("fileSize")
    release_tag = identity.get("releaseTag")
    source_sha = identity.get("sourceSha")
    if not isinstance(plugin_name, str) or not PLUGIN_NAME_RE.fullmatch(plugin_name):
        raise ContractError("pluginName is invalid")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ContractError("version must use X.Y")
    if not isinstance(version_id, str) or not UUID_RE.fullmatch(version_id):
        raise ContractError("versionId is not a canonical UUID")
    if not isinstance(checksum, str) or not CHECKSUM_RE.fullmatch(checksum):
        raise ContractError("checksum is not a canonical SHA-256")
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size <= 0:
        raise ContractError("fileSize must be a positive integer")
    if release_tag != f"v{version}":
        raise ContractError("releaseTag does not match version")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise ContractError("sourceSha is not a lowercase 40-hex commit")
    return identity


def parse_dev100_evidence_log(
    log_text: str,
    expected: Mapping[str, Any],
    *,
    allow_other_plugin_records: bool = False,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        marker_index = line.find(LOG_MARKER)
        if marker_index < 0:
            continue
        raw_json = line[marker_index + len(LOG_MARKER):].strip()
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ContractError("DEV100 evidence JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise ContractError("DEV100 evidence payload is not an object")
        records.append(validate_immutable_identity(payload))
    canonical_expected = validate_immutable_identity(expected)
    if allow_other_plugin_records:
        matching_records = [
            record
            for record in records
            if record["pluginName"] == canonical_expected["pluginName"]
        ]
        if len(matching_records) != 1:
            raise ContractError(
                "exactly one DEV100 evidence record for the expected plugin is required"
            )
        selected = matching_records[0]
    else:
        if len(records) != 1:
            raise ContractError("exactly one DEV100 evidence record is required")
        selected = records[0]
    if selected != canonical_expected:
        raise ContractError("DEV100 evidence identity drift")
    return selected


def expected_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "pluginName": args.plugin_name,
        "version": args.plugin_version,
        "versionId": args.version_id,
        "checksum": args.checksum,
        "fileSize": args.file_size,
        "releaseTag": args.release_tag,
        "sourceSha": args.source_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate immutable plugin promotion evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-dev100-log")
    verify.add_argument("--log", required=True, type=Path)
    verify.add_argument("--plugin-name", required=True)
    verify.add_argument("--plugin-version", required=True)
    verify.add_argument("--version-id", required=True)
    verify.add_argument("--checksum", required=True)
    verify.add_argument("--file-size", required=True, type=int)
    verify.add_argument("--release-tag", required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--allow-other-plugin-records", action="store_true")
    args = parser.parse_args()
    if args.command == "verify-dev100-log":
        try:
            evidence = parse_dev100_evidence_log(
                args.log.read_text(encoding="utf-8"),
                expected_from_args(args),
                allow_other_plugin_records=args.allow_other_plugin_records,
            )
        except (OSError, ContractError) as exc:
            parser.error(str(exc))
        print(json.dumps(evidence, separators=(",", ":"), sort_keys=True))
        return 0
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
