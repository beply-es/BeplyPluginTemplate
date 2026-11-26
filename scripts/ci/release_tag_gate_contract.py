#!/usr/bin/env python3
"""Contract helpers for verifying consumer release-tag-gate alignment with tests.yml."""
from __future__ import annotations

import itertools
import json
import re
from typing import Any

import yaml

MATRIX_EXPR_RE = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
FS_REFS_EXPR = "${{ fromJSON(needs.quality_contract.outputs.fs_refs) }}"
REUSABLE_GATE_PIN_RE = re.compile(
    r"^beply-es/BeplyPluginTemplate/\.github/workflows/reusable-release-tag-gate\.yml@([0-9a-f]{40})$"
)
LOCAL_GATE_USES = "./.github/workflows/reusable-release-tag-gate.yml"


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


def _expand_job_names(
    job_key: str,
    job_cfg: dict[str, Any],
    matrix_json: dict[str, Any] | None,
) -> list[str]:
    base_name = job_cfg.get("name")
    strategy = job_cfg.get("strategy") or {}
    matrix = strategy.get("matrix")
    if not isinstance(matrix, dict) or not matrix:
        return [str(base_name) if base_name else job_key]

    axes: list[tuple[str, list[str]]] = []
    for axis_key, raw_values in matrix.items():
        if axis_key in {"include", "exclude"}:
            continue
        if isinstance(raw_values, list):
            axes.append((axis_key, [str(v) for v in raw_values]))
        elif isinstance(raw_values, str) and raw_values.strip() == FS_REFS_EXPR:
            axes.append((axis_key, _required_fs_refs(matrix_json)))
        else:
            raise ValueError(
                f"Job {job_key!r} matrix axis {axis_key!r} uses unsupported dynamic value: {raw_values!r}"
            )

    names: list[str] = []
    axis_keys = [k for k, _ in axes]
    for combo in itertools.product(*(vals for _, vals in axes)):
        mapping = dict(zip(axis_keys, combo))
        if base_name:
            rendered = MATRIX_EXPR_RE.sub(lambda m: mapping[m.group(1)], str(base_name))
            names.append(rendered)
        else:
            names.append(f"{job_key} ({', '.join(combo)})")
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
        expanded = _expand_job_names(str(job_key), job_cfg, matrix_json)
        if job_cfg.get("continue-on-error") is True:
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
