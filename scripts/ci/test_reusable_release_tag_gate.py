#!/usr/bin/env python3
"""Contract and executable security tests for reusable-release-tag-gate.yml."""
from __future__ import annotations

import io
import json
import re
import textwrap
import types
import unittest
import urllib.error
from pathlib import Path

import yaml

from scripts.ci.release_tag_gate_contract import (
    extract_tests_job_names,
    validate_consumer_release_tag_gate,
)

ROOT = Path(__file__).resolve().parents[2]
GATE_WORKFLOW = ROOT / ".github" / "workflows" / "reusable-release-tag-gate.yml"
TEMPLATE_RELEASE = ROOT / ".github" / "workflows" / "release.yml"
TEMPLATE_TESTS = ROOT / ".github" / "workflows" / "tests.yml"
TEMPLATE_MATRIX = ROOT / ".beply" / "facturascripts-matrix.json"

SHA40 = "a" * 40
OTHER_SHA40 = "b" * 40
TAG_OBJ_SHA40 = "c" * 40
PIN_SHA40 = "d" * 40
SAMPLE_REPO = "beply-es/SamplePlugin"
SAMPLE_JOBS = ("guardrails", "unit", "runtime (baseline)", "runtime (2026.7)", "e2e")

EXPECTED_PERMISSIONS = {"actions": "read", "contents": "read"}
EXPECTED_ENV = {
    "GITHUB_TOKEN": "${{ github.token }}",
    "REPOSITORY": "${{ github.repository }}",
    "TARGET_SHA": "${{ github.sha }}",
    "TARGET_REF": "${{ github.ref }}",
    "TARGET_REF_NAME": "${{ github.ref_name }}",
    "TARGET_REF_TYPE": "${{ github.ref_type }}",
    "TARGET_EVENT": "${{ github.event_name }}",
    "CURRENT_RUN_ID": "${{ github.run_id }}",
    "EXPECTED_REPO": "${{ inputs.expected_repo }}",
    "EXPECTED_JOBS_JSON": "${{ inputs.expected_jobs }}",
    "OPTIONAL_JOBS_JSON": "${{ inputs.optional_jobs }}",
    "TESTS_WORKFLOW_FILE": "${{ inputs.tests_workflow_file }}",
    "TIMEOUT_MINUTES": "${{ inputs.timeout_minutes }}",
}
ARC_ONLY_RUNNER = (
    "${{ vars.BEPLY_GHA_RUNNER == 'arc-runner-prio' && 'arc-runner-prio' || 'arc-runner-set' }}"
)


def extract_gate_module(workflow_text: str) -> types.ModuleType:
    doc = yaml.safe_load(workflow_text)
    steps = doc["jobs"]["verify_tests"]["steps"]
    gate_step = next(step for step in steps if step.get("name") == "Wait for exact Tests workflow")
    match = re.search(r"python3 - <<'PY'\n(.*?)\nPY", gate_step["run"], re.S)
    if not match:
        raise AssertionError("Could not extract inline Python script from reusable-release-tag-gate.yml")
    source = textwrap.dedent(match.group(1))
    module = types.ModuleType("reusable_release_tag_gate")
    exec(compile(source, str(GATE_WORKFLOW), "exec"), module.__dict__)
    return module


def validate_reusable_gate_workflow(workflow_text: str) -> None:
    doc = yaml.safe_load(workflow_text)
    assert isinstance(doc, dict), "workflow must be a YAML mapping"
    triggers = doc[True] if True in doc else doc.get("on")
    assert isinstance(triggers, dict) and list(triggers.keys()) == ["workflow_call"], (
        "reusable gate must trigger only on workflow_call"
    )
    inputs = triggers["workflow_call"]["inputs"]
    assert inputs["expected_repo"]["required"] is True
    assert inputs["expected_jobs"]["required"] is True

    jobs = doc.get("jobs") or {}
    assert list(jobs.keys()) == ["verify_tests"], f"expected single verify_tests job, got {list(jobs.keys())}"
    job = jobs["verify_tests"]
    # R1: verify_tests must never have `if:` so non-tag runs fail closed visibly.
    assert "if" not in job, "verify_tests must not declare if:"
    # C3: explicit minimal permissions (never inherit or grant contents: write).
    assert job.get("permissions") == EXPECTED_PERMISSIONS, (
        f"verify_tests permissions must be {EXPECTED_PERMISSIONS}, got {job.get('permissions')}"
    )
    assert job.get("runs-on") == ARC_ONLY_RUNNER, "verify_tests must use ARC-only runner expression"
    assert job.get("timeout-minutes") == 50

    steps = job.get("steps") or []
    assert len(steps) == 1, f"verify_tests must have exactly 1 step (no checkout/cache), got {len(steps)}"
    step = steps[0]
    # No checkout (never ref: main), no cache, no external actions.
    for forbidden in ("actions/checkout", "actions/cache", "package-manager-cache: true", "ref: main"):
        assert forbidden not in workflow_text, f"forbidden construct in reusable gate: {forbidden}"
    assert "uses" not in step, "gate step must not invoke external actions"
    # C4: exact env whitelist for all github.* and inputs.* expressions.
    assert step.get("env") == EXPECTED_ENV, (
        f"verify_tests env must match exact whitelist {EXPECTED_ENV}, got {step.get('env')}"
    )
    # Zero `${{ ... }}` interpolation inside the `run:` script body.
    assert "${{" not in step.get("run", ""), "run script must not interpolate GitHub expressions directly"


def http_error(url: str, code: int, msg: str = "Error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, msg, {}, io.BytesIO(b"{}"))


def make_env(**overrides: str) -> dict[str, str]:
    base = {
        "GITHUB_TOKEN": "synthetic-ci-token",
        "REPOSITORY": SAMPLE_REPO,
        "EXPECTED_REPO": SAMPLE_REPO,
        "EXPECTED_JOBS_JSON": json.dumps(list(SAMPLE_JOBS)),
        "OPTIONAL_JOBS_JSON": "[]",
        "TESTS_WORKFLOW_FILE": "tests.yml",
        "TIMEOUT_MINUTES": "49",
        "TARGET_SHA": SHA40,
        "TARGET_REF": "refs/tags/v1.0",
        "TARGET_REF_NAME": "v1.0",
        "TARGET_REF_TYPE": "tag",
        "TARGET_EVENT": "push",
        "CURRENT_RUN_ID": "900",
    }
    base.update(overrides)
    return base


def make_valid_responses(
    repo: str = SAMPLE_REPO,
    tag: str = "v1.0",
    sha: str = SHA40,
    runs=None,
    jobs=None,
    workflow_file: str = "tests.yml",
):
    heads_url = f"https://api.github.com/repos/{repo}/git/ref/heads/{tag}"
    runs_url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/runs"
        f"?head_sha={sha}&per_page=100"
    )
    jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/100/attempts/1/jobs?per_page=100"
    if runs is None:
        runs = [{
            "id": 100,
            "run_attempt": 1,
            "head_sha": sha,
            "head_branch": tag,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }]
    if jobs is None:
        jobs_payload = {
            "total_count": len(SAMPLE_JOBS),
            "jobs": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in SAMPLE_JOBS
            ],
        }
    else:
        jobs_payload = {"total_count": len(jobs), "jobs": jobs}
    return {
        f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}": {
            "ref": f"refs/tags/{tag}",
            "object": {"type": "commit", "sha": sha},
        },
        heads_url: http_error(heads_url, 404, "Not Found"),
        runs_url: {"workflow_runs": runs},
        jobs_url: jobs_payload,
    }


def make_fake_get_json(responses: dict, calls: list[str] | None = None):
    def fake_get_json(endpoint: str):
        if calls is not None:
            calls.append(endpoint)
        if endpoint not in responses:
            raise AssertionError(f"Unexpected API call: {endpoint}")
        value = responses[endpoint]
        if isinstance(value, Exception):
            raise value
        return value

    return fake_get_json


class ReusableReleaseTagGateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = GATE_WORKFLOW.read_text(encoding="utf-8")
        cls.gate = extract_gate_module(cls.workflow_text)

    def test_reusable_workflow_satisfies_security_contract(self) -> None:
        validate_reusable_gate_workflow(self.workflow_text)

    def test_reusable_workflow_contract_rejects_downgrades(self) -> None:
        mutations = (
            self.workflow_text.replace("      contents: read\n", "      contents: write\n"),
            self.workflow_text.replace("    permissions:\n      actions: read\n      contents: read\n", ""),
            self.workflow_text.replace(
                "TARGET_REF_TYPE: ${{ github.ref_type }}",
                "TARGET_REF_TYPE: ${{ github.event_name }}",
            ),
            self.workflow_text.replace(
                "CURRENT_RUN_ID: ${{ github.run_id }}\n",
                "CURRENT_RUN_ID: ${{ github.run_id }}\n          EXTRA_ACTOR: ${{ github.actor }}\n",
            ),
            self.workflow_text.replace(
                "    name: Verify Tests Workflow\n",
                "    name: Verify Tests Workflow\n    if: github.ref_type == 'tag'\n",
            ),
            self.workflow_text.replace(
                "    steps:\n",
                "    steps:\n      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n        with:\n          ref: main\n",
            ),
        )
        for idx, mutated in enumerate(mutations):
            with self.subTest(mutation=idx), self.assertRaises(AssertionError):
                validate_reusable_gate_workflow(mutated)

    def test_valid_tag_passes_for_push_and_recovery_dispatch(self) -> None:
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                ok, reason = self.gate.verify_release_tests(
                    make_env(TARGET_EVENT=event),
                    get_json=make_fake_get_json(make_valid_responses()),
                    sleep=lambda _: None,
                    max_polls=1,
                )
                self.assertTrue(ok, reason)
                self.assertIn("Verified green tag push Tests run 100", reason)

    def test_annotated_tag_peels_to_commit_and_passes(self) -> None:
        responses = make_valid_responses()
        responses[f"https://api.github.com/repos/{SAMPLE_REPO}/git/ref/tags/v1.0"] = {
            "ref": "refs/tags/v1.0",
            "object": {"type": "tag", "sha": TAG_OBJ_SHA40},
        }
        responses[f"https://api.github.com/repos/{SAMPLE_REPO}/git/tags/{TAG_OBJ_SHA40}"] = {
            "object": {"type": "commit", "sha": SHA40},
        }
        ok, reason = self.gate.verify_release_tests(
            make_env(TARGET_EVENT="workflow_dispatch"),
            get_json=make_fake_get_json(responses),
            sleep=lambda _: None,
            max_polls=1,
        )
        self.assertTrue(ok, reason)

    def test_ref_type_branch_and_non_refs_tags_rejected_before_network(self) -> None:
        for overrides, expected_msg in (
            ({"TARGET_REF_TYPE": "branch"}, "Refusing non-tag ref type: 'branch'"),
            ({"TARGET_REF": "refs/heads/v1.0"}, "TARGET_REF 'refs/heads/v1.0' must equal refs/tags/v1.0"),
        ):
            with self.subTest(overrides=overrides):
                calls: list[str] = []
                ok, reason = self.gate.verify_release_tests(
                    make_env(TARGET_EVENT="workflow_dispatch", **overrides),
                    get_json=make_fake_get_json(make_valid_responses(), calls=calls),
                    sleep=lambda _: None,
                    max_polls=1,
                )
                self.assertFalse(ok)
                self.assertEqual(reason, expected_msg)
                self.assertEqual(calls, [])

    def test_colliding_branch_rejected_fail_closed(self) -> None:
        responses = make_valid_responses()
        responses[f"https://api.github.com/repos/{SAMPLE_REPO}/git/ref/heads/v1.0"] = {
            "ref": "refs/heads/v1.0",
            "object": {"type": "commit", "sha": SHA40},
        }
        ok, reason = self.gate.verify_release_tests(
            make_env(),
            get_json=make_fake_get_json(responses),
            sleep=lambda _: None,
            max_polls=1,
        )
        self.assertFalse(ok)
        self.assertIn("Colliding branch refs/heads/v1.0", reason)

    def test_branch_collision_http_500_and_403_fail_closed(self) -> None:
        heads_url = f"https://api.github.com/repos/{SAMPLE_REPO}/git/ref/heads/v1.0"
        for code, msg in ((500, "Internal Server Error"), (403, "Forbidden")):
            with self.subTest(http_code=code):
                responses = make_valid_responses()
                responses[heads_url] = http_error(heads_url, code, msg)
                calls: list[str] = []
                ok, reason = self.gate.verify_release_tests(
                    make_env(),
                    get_json=make_fake_get_json(responses, calls=calls),
                    sleep=lambda _: None,
                    max_polls=1,
                )
                self.assertFalse(ok)
                self.assertIn("Failed to verify absence of branch refs/heads/v1.0", reason)
                self.assertEqual(len(calls), 2)

    def test_wrong_identity_or_missing_tests_cannot_pass(self) -> None:
        good_run = {
            "id": 100,
            "run_attempt": 1,
            "head_sha": SHA40,
            "head_branch": "v1.0",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        cases = (
            ("empty_runs", []),
            ("wrong_head_sha", [{**good_run, "head_sha": OTHER_SHA40}]),
            ("wrong_head_branch_main", [{**good_run, "head_branch": "main"}]),
            ("wrong_event_pull_request", [{**good_run, "event": "pull_request"}]),
            ("wrong_event_workflow_dispatch", [{**good_run, "event": "workflow_dispatch"}]),
            ("same_current_run_id", [{**good_run, "id": 900}]),
            ("conclusion_failure", [{**good_run, "conclusion": "failure"}]),
            ("conclusion_skipped", [{**good_run, "conclusion": "skipped"}]),
        )
        for label, runs in cases:
            with self.subTest(case=label):
                ok, reason = self.gate.verify_release_tests(
                    make_env(),
                    get_json=make_fake_get_json(make_valid_responses(runs=runs)),
                    sleep=lambda _: None,
                    max_polls=1,
                )
                self.assertFalse(ok, f"{label} must fail closed: {reason}")

    def test_latest_run_wins_over_older_success(self) -> None:
        good_run = {
            "id": 100,
            "run_attempt": 1,
            "head_sha": SHA40,
            "head_branch": "v1.0",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        for state in (
            {"status": "completed", "conclusion": "failure"},
            {"status": "in_progress", "conclusion": None},
        ):
            ok, _ = self.gate.verify_release_tests(
                make_env(),
                get_json=make_fake_get_json(make_valid_responses(runs=[good_run, {**good_run, "id": 200, **state}])),
                sleep=lambda _: None,
                max_polls=1,
            )
            self.assertFalse(ok)

    def test_all_expected_jobs_must_succeed_and_optional_advisory_jobs_must_complete(self) -> None:
        good = [{"name": n, "status": "completed", "conclusion": "success"} for n in SAMPLE_JOBS]
        for jobs in (
            [],
            good[:-1],
            good + good[:1],
            [{**j, "conclusion": "skipped"} if j["name"] == "e2e" else j for j in good],
            [{**j, "status": "in_progress"} if j["name"] == "unit" else j for j in good],
        ):
            with self.subTest(jobs=jobs):
                ok, _ = self.gate.verify_release_tests(
                    make_env(),
                    get_json=make_fake_get_json(make_valid_responses(jobs=jobs)),
                    sleep=lambda _: None,
                    max_polls=1,
                )
                self.assertFalse(ok)

        # Advisory job with continue-on-error: completed/failure is allowed only when listed in OPTIONAL_JOBS_JSON.
        advisory_jobs = good + [{"name": "PHP 8.4 Compatibility", "status": "completed", "conclusion": "failure"}]
        ok_without_opt, _ = self.gate.verify_release_tests(
            make_env(),
            get_json=make_fake_get_json(make_valid_responses(jobs=advisory_jobs)),
            sleep=lambda _: None,
            max_polls=1,
        )
        self.assertFalse(ok_without_opt)

        ok_with_opt, reason = self.gate.verify_release_tests(
            make_env(OPTIONAL_JOBS_JSON='["PHP 8.4 Compatibility"]'),
            get_json=make_fake_get_json(make_valid_responses(jobs=advisory_jobs)),
            sleep=lambda _: None,
            max_polls=1,
        )
        self.assertTrue(ok_with_opt, reason)

    def test_invalid_inputs_and_redirects_fail_closed(self) -> None:
        for overrides in (
            {"REPOSITORY": "beply-es/OtherRepo"},
            {"EXPECTED_REPO": "not-a-repo"},
            {"EXPECTED_JOBS_JSON": "[]"},
            {"EXPECTED_JOBS_JSON": "not-json"},
            {"TESTS_WORKFLOW_FILE": "../evil.yml"},
            {"TARGET_SHA": "short"},
            {"TARGET_REF_NAME": "main"},
            {"GITHUB_TOKEN": ""},
        ):
            with self.subTest(overrides=overrides):
                calls: list[str] = []
                ok, _ = self.gate.verify_release_tests(
                    make_env(**overrides),
                    get_json=make_fake_get_json(make_valid_responses(), calls=calls),
                    sleep=lambda _: None,
                    max_polls=1,
                )
                self.assertFalse(ok)
                self.assertEqual(calls, [])

        handler = self.gate._NoRedirect()
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(None, None, 302, "redirect", {}, "https://untrusted.invalid/")


class ConsumerExpectedJobsContractTests(unittest.TestCase):
    def test_template_release_expected_jobs_match_template_tests_yml(self) -> None:
        release_text = TEMPLATE_RELEASE.read_text(encoding="utf-8")
        tests_text = TEMPLATE_TESTS.read_text(encoding="utf-8")
        matrix_json = json.loads(TEMPLATE_MATRIX.read_text(encoding="utf-8"))
        result = validate_consumer_release_tag_gate(
            release_text,
            tests_text,
            expected_repo="beply-es/BeplyPluginTemplate",
            matrix_json=matrix_json,
            allow_local_uses=True,
        )
        self.assertEqual(result["optional_jobs"], ["PHP 8.4 Compatibility"])
        self.assertIn("Quality Contract", result["expected_jobs"])
        self.assertIn("Lint FS v2026.3", result["expected_jobs"])
        self.assertIn("Unit FS v2026.2 PHP 8.2", result["expected_jobs"])
        self.assertIn("E2E FS v2026.3", result["expected_jobs"])

    def test_consumer_contract_matches_marketplace_tests_and_rejects_drift(self) -> None:
        consumer_tests = textwrap.dedent("""\
            name: Tests
            on:
              push:
                tags: ['v*']
            jobs:
              guardrails:
                runs-on: arc-runner-set
              unit:
                runs-on: arc-runner-set
              runtime:
                runs-on: arc-runner-set
                strategy:
                  matrix:
                    core-profile: ['baseline', '2026.7']
              e2e:
                runs-on: arc-runner-set
        """)
        required, advisory = extract_tests_job_names(consumer_tests)
        self.assertEqual(required, frozenset(SAMPLE_JOBS))
        self.assertEqual(advisory, frozenset())

        consumer_release = textwrap.dedent(f"""\
            name: Release Plugin
            on:
              push:
                tags: ['v*']
              workflow_dispatch:
            jobs:
              verify_tests:
                name: Verify Tests Workflow
                uses: beply-es/BeplyPluginTemplate/.github/workflows/reusable-release-tag-gate.yml@{PIN_SHA40}
                with:
                  expected_repo: {SAMPLE_REPO}
                  expected_jobs: '{json.dumps(list(SAMPLE_JOBS))}'
        """)
        result = validate_consumer_release_tag_gate(
            consumer_release,
            consumer_tests,
            expected_repo=SAMPLE_REPO,
        )
        self.assertEqual(result["pinned_sha"], PIN_SHA40)

        # Drift: missing a job from expected_jobs must fail closed.
        drifted_release = consumer_release.replace(', "e2e"', "")
        with self.assertRaisesRegex(AssertionError, "EXPECTED_JOBS mismatch"):
            validate_consumer_release_tag_gate(
                drifted_release,
                consumer_tests,
                expected_repo=SAMPLE_REPO,
            )

        # Unpinned ref (main) must fail closed.
        unpinned_release = consumer_release.replace(f"@{PIN_SHA40}", "@main")
        with self.assertRaisesRegex(AssertionError, "40-hex SHA"):
            validate_consumer_release_tag_gate(
                unpinned_release,
                consumer_tests,
                expected_repo=SAMPLE_REPO,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
