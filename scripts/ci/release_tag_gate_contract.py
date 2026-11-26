#!/usr/bin/env python3
"""Contract helpers for verifying consumer release-tag-gate alignment with tests.yml."""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

MATRIX_EXPR_RE = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
ANY_EXPR_RE = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
FS_REFS_EXPR = "${{ fromJSON(needs.quality_contract.outputs.fs_refs) }}"
REUSABLE_GATE_PIN_RE = re.compile(
    r"^beply-es/BeplyPluginTemplate/\.github/workflows/reusable-release-tag-gate\.yml@([0-9a-f]{40})$"
)
LOCAL_GATE_USES = "./.github/workflows/reusable-release-tag-gate.yml"


def _scalar_to_str(value: Any, *, context: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"{context} must be a scalar value, got {type(value).__name__}: {value!r}")


def _required_fs_refs(matrix_json: dict[str, Any] | None) -> list[str]:
    if not matrix_json:
        raise ValueError("matrix_json is required when tests.yml references quality_contract.outputs.fs_refs")
    supported = matrix_json.get("supported")
    if not isinstance(supported, list):
        raise ValueError("facturascripts-matrix.json must contain a 'supported' list")
    refs = [
        item["ref"]
        for item in supported
        if isinstance(item, dict) and item.get("required") is True and isinstance(item.get("ref"), str)
    ]
    if not refs:
        raise ValueError("facturascripts-matrix.json must contain at least one required ref")
    return refs


def _parse_matrix_entry_list(raw: Any, *, job_key: str, field_name: str) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise ValueError(f"Job {job_key!r} matrix.{field_name} must be a static list of mappings, got {raw!r}")
    entries: list[dict[str, str]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict) or not item:
            raise ValueError(f"Job {job_key!r} matrix.{field_name}[{idx}] must be a non-empty mapping")
        entries.append(
            {
                str(k): _scalar_to_str(v, context=f"Job {job_key!r} matrix.{field_name}[{idx}].{k}")
                for k, v in item.items()
            }
        )
    return entries


def _expand_job_names(
    job_key: str,
    job_cfg: dict[str, Any],
    matrix_json: dict[str, Any] | None,
) -> list[str]:
    base_name = job_cfg.get("name")
    if base_name is not None and not isinstance(base_name, str):
        raise ValueError(f"Job {job_key!r} name must be a string, got {type(base_name).__name__}")

    strategy = job_cfg.get("strategy")
    if strategy is None:
        strategy = {}
    elif not isinstance(strategy, dict):
        raise ValueError(f"Job {job_key!r} strategy must be a mapping, got {strategy!r}")

    if "matrix" not in strategy or strategy.get("matrix") is None:
        if base_name and ANY_EXPR_RE.search(base_name):
            raise ValueError(f"Job {job_key!r} uses unsupported dynamic expression in name: {base_name!r}")
        return [base_name if base_name else job_key]

    matrix = strategy["matrix"]
    if not isinstance(matrix, dict) or not matrix:
        raise ValueError(f"Job {job_key!r} strategy.matrix must be a static non-empty mapping, got {matrix!r}")

    axes: list[tuple[str, list[str]]] = []
    for axis_key, raw_values in matrix.items():
        if axis_key in {"include", "exclude"}:
            continue
        if isinstance(raw_values, list):
            if not raw_values:
                raise ValueError(f"Job {job_key!r} matrix axis {axis_key!r} must not be empty")
            axes.append(
                (
                    str(axis_key),
                    [
                        _scalar_to_str(v, context=f"Job {job_key!r} matrix.{axis_key}")
                        for v in raw_values
                    ],
                )
            )
        elif isinstance(raw_values, str) and raw_values.strip() == FS_REFS_EXPR:
            axes.append((str(axis_key), _required_fs_refs(matrix_json)))
        else:
            raise ValueError(
                f"Job {job_key!r} matrix axis {axis_key!r} uses unsupported dynamic value: {raw_values!r}"
            )

    axis_keys = [k for k, _ in axes]
    combos: list[dict[str, str]] = (
        [dict(zip(axis_keys, combo)) for combo in itertools.product(*(vals for _, vals in axes))]
        if axes
        else []
    )

    if "exclude" in matrix and matrix["exclude"] is not None:
        exclusions = _parse_matrix_entry_list(matrix["exclude"], job_key=job_key, field_name="exclude")
        filtered: list[dict[str, str]] = []
        for combo in combos:
            excluded = any(
                all(k in combo and combo[k] == v for k, v in ex.items())
                for ex in exclusions
            )
            if not excluded:
                filtered.append(combo)
        combos = filtered

    if "include" in matrix and matrix["include"] is not None:
        inclusions = _parse_matrix_entry_list(matrix["include"], job_key=job_key, field_name="include")
        for inc in inclusions:
            matched_any = False
            for combo in combos:
                if all(combo[k] == v for k, v in inc.items() if k in combo):
                    matched_any = True
                    for k, v in inc.items():
                        if k not in combo:
                            combo[k] = v
            if not matched_any:
                combos.append(dict(inc))

    if not combos:
        raise ValueError(f"Job {job_key!r} matrix expanded to zero combinations")

    has_matrix_expr = bool(base_name and MATRIX_EXPR_RE.search(base_name))
    names: list[str] = []
    for combo in combos:
        if has_matrix_expr:
            def _replace(match: re.Match[str], _combo: dict[str, str] = combo) -> str:
                key = match.group(1)
                if key not in _combo:
                    raise ValueError(
                        f"Job {job_key!r} name references missing matrix key {key!r} in combo {_combo!r}"
                    )
                return _combo[key]

            rendered = MATRIX_EXPR_RE.sub(_replace, str(base_name))
            if ANY_EXPR_RE.search(rendered):
                raise ValueError(f"Job {job_key!r} name has unsupported expression after matrix expansion: {rendered!r}")
            names.append(rendered)
        else:
            if base_name and ANY_EXPR_RE.search(base_name):
                raise ValueError(f"Job {job_key!r} uses unsupported dynamic expression in name: {base_name!r}")
            prefix = base_name if base_name else job_key
            if axis_keys:
                suffix_vals = [combo[k] for k in axis_keys if k in combo]
                if not suffix_vals:
                    suffix_vals = list(combo.values())
            else:
                suffix_vals = list(combo.values())
            names.append(f"{prefix} ({', '.join(suffix_vals)})")
    return names


def extract_tests_job_names(
    tests_yaml_text: str,
    *,
    matrix_json: dict[str, Any] | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Return (required_job_names, advisory_job_names) as emitted by GitHub Actions for tests.yml."""
    doc = yaml.safe_load(tests_yaml_text)
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        raise ValueError("tests.yml must define a top-level 'jobs' mapping")

    required: list[str] = []
    advisory: list[str] = []
    for job_key, job_cfg in doc["jobs"].items():
        if not isinstance(job_cfg, dict):
            raise ValueError(f"Job {job_key!r} in tests.yml must be a mapping")
        continue_on_error = job_cfg.get("continue-on-error", False)
        if not isinstance(continue_on_error, bool):
            raise ValueError(
                f"Job {job_key!r} continue-on-error must be a static boolean, got {continue_on_error!r}"
            )
        expanded = _expand_job_names(str(job_key), job_cfg, matrix_json)
        if continue_on_error:
            advisory.extend(expanded)
        else:
            required.extend(expanded)

    return frozenset(required), frozenset(advisory)


def validate_consumer_release_tag_gate(
    release_yaml_text: str,
    tests_yaml_text: str,
    *,
    expected_repo: str,
    matrix_json: dict[str, Any] | None = None,
    allow_local_uses: bool = False,
) -> dict[str, Any]:
    """Validate that a consumer's release.yml invokes reusable-release-tag-gate with exact job parity."""
    doc = yaml.safe_load(release_yaml_text)
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        raise AssertionError("release.yml must define a top-level 'jobs' mapping")

    jobs = doc["jobs"]
    if "verify_tests" not in jobs or not isinstance(jobs["verify_tests"], dict):
        raise AssertionError("release.yml must define a 'verify_tests' job")

    gate_job = jobs["verify_tests"]
    if "if" in gate_job:
        raise AssertionError("verify_tests must not declare 'if:' (must execute and fail closed on non-tag refs)")

    uses = gate_job.get("uses")
    if not isinstance(uses, str):
        raise AssertionError("verify_tests must call reusable-release-tag-gate.yml via 'uses:'")
    if allow_local_uses and uses == LOCAL_GATE_USES:
        pinned_sha = None
    else:
        match = REUSABLE_GATE_PIN_RE.fullmatch(uses)
        if not match:
            raise AssertionError(
                f"verify_tests must pin reusable-release-tag-gate.yml by 40-hex SHA, got {uses!r}"
            )
        pinned_sha = match.group(1)

    with_cfg = gate_job.get("with") or {}
    if not isinstance(with_cfg, dict):
        raise AssertionError("verify_tests must pass 'with:' inputs")
    if with_cfg.get("expected_repo") != expected_repo:
        raise AssertionError(
            f"verify_tests expected_repo must be {expected_repo!r}, got {with_cfg.get('expected_repo')!r}"
        )

    raw_expected = with_cfg.get("expected_jobs")
    if not isinstance(raw_expected, str):
        raise AssertionError("verify_tests must pass expected_jobs as a JSON array string")
    declared_required = frozenset(json.loads(raw_expected))

    raw_optional = with_cfg.get("optional_jobs", "[]")
    if not isinstance(raw_optional, str):
        raise AssertionError("verify_tests optional_jobs must be a JSON array string")
    declared_optional = frozenset(json.loads(raw_optional))

    actual_required, actual_advisory = extract_tests_job_names(tests_yaml_text, matrix_json=matrix_json)
    if declared_required != actual_required:
        raise AssertionError(
            f"EXPECTED_JOBS mismatch against tests.yml: declared={sorted(declared_required)}, "
            f"actual={sorted(actual_required)}"
        )
    if declared_optional != actual_advisory:
        raise AssertionError(
            f"OPTIONAL_JOBS mismatch against tests.yml advisory jobs: declared={sorted(declared_optional)}, "
            f"actual={sorted(actual_advisory)}"
        )

    return {
        "pinned_sha": pinned_sha,
        "expected_jobs": sorted(declared_required),
        "optional_jobs": sorted(declared_optional),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate consumer release.yml reusable-release-tag-gate parity against tests.yml."
    )
    parser.add_argument("--release", type=Path, default=Path(".github/workflows/release.yml"))
    parser.add_argument("--tests", type=Path, default=Path(".github/workflows/tests.yml"))
    parser.add_argument("--expected-repo", required=True)
    parser.add_argument("--matrix", type=Path, default=None)
    parser.add_argument("--allow-local-uses", action="store_true")
    args = parser.parse_args(argv)

    matrix_json = json.loads(args.matrix.read_text(encoding="utf-8")) if args.matrix else None
    result = validate_consumer_release_tag_gate(
        args.release.read_text(encoding="utf-8"),
        args.tests.read_text(encoding="utf-8"),
        expected_repo=args.expected_repo,
        matrix_json=matrix_json,
        allow_local_uses=args.allow_local_uses,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
