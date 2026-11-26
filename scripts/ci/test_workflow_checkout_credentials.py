import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Matches network-touching git invocations (including command substitutions $(git ...),
# shell conditionals like `if git ls-remote ...`, and flags like -C/-c before subcommand).
GIT_NETWORK_CMD_RE = re.compile(
    r"(?:^|[;&|(`{\s]|\$\()git\b[^\n;&|)`}]*\b(fetch|pull|push|ls-remote|clone)\b",
)

EXPLICIT_GIT_AUTH_RE = re.compile(
    r"-c\s+[\"']?http(?:\.https://github\.com/)?\.extraheader=AUTHORIZATION:",
    re.IGNORECASE,
)


def iter_logical_lines(run_script: str) -> list[tuple[int, str]]:
    """Collapse shell backslash line continuations into logical lines with starting line numbers."""
    logical: list[tuple[int, str]] = []
    buf: list[str] = []
    start_line = 1
    for line_no, raw_line in enumerate(run_script.splitlines(), start=1):
        if not buf:
            start_line = line_no
        rstripped = raw_line.rstrip()
        if rstripped.endswith("\\"):
            buf.append(rstripped[:-1])
        else:
            buf.append(raw_line)
            logical.append((start_line, " ".join(part.strip() for part in buf if part.strip())))
            buf = []
    if buf:
        logical.append((start_line, " ".join(part.strip() for part in buf if part.strip())))
    return logical


def find_workflow_credential_violations(workflow_name: str, data: dict) -> list[str]:
    violations: list[str] = []
    if not isinstance(data, dict):
        return violations

    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return violations

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            step_label = step.get("name") or f"step #{idx}"
            uses = str(step.get("uses") or "").strip()
            if uses.startswith("actions/checkout@") or uses == "actions/checkout":
                with_cfg = step.get("with")
                persist = with_cfg.get("persist-credentials") if isinstance(with_cfg, dict) else None
                if persist is not False:
                    violations.append(
                        f"{workflow_name}::{job_id}::{step_label}: actions/checkout must set 'persist-credentials: false' (got {persist!r})"
                    )

            run_script = step.get("run")
            if not isinstance(run_script, str):
                continue
            env_cfg = step.get("env") if isinstance(step.get("env"), dict) else {}
            has_token_env = any(
                k in env_cfg for k in ("GH_TOKEN", "GITHUB_TOKEN")
            )
            for line_no, stripped in iter_logical_lines(run_script):
                if not stripped or stripped.startswith("#"):
                    continue
                for match in GIT_NETWORK_CMD_RE.finditer(stripped):
                    cmd_fragment = match.group(0).strip()
                    has_extraheader = bool(EXPLICIT_GIT_AUTH_RE.search(cmd_fragment))
                    if not (has_extraheader and has_token_env):
                        violations.append(
                            f"{workflow_name}::{job_id}::{step_label} (run line {line_no}): "
                            f"network git command without explicit per-command auth (http.extraheader + GH_TOKEN/GITHUB_TOKEN): {stripped}"
                        )

    return violations


def scan_workflows_dir(workflows_dir: Path = WORKFLOWS_DIR) -> list[str]:
    violations: list[str] = []
    for path in sorted(workflows_dir.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        violations.extend(find_workflow_credential_violations(path.name, data))
    return violations


class WorkflowCheckoutCredentialsContractTest(unittest.TestCase):
    def test_all_repo_workflows_enforce_persist_credentials_false_and_explicit_git_auth(self) -> None:
        violations = scan_workflows_dir(WORKFLOWS_DIR)
        self.assertEqual(
            [],
            violations,
            "Workflow credential hygiene violations found:\n" + "\n".join(violations),
        )

    def test_mutant_m1_missing_persist_credentials_is_rejected(self) -> None:
        wf = {
            "jobs": {
                "build": {
                    "steps": [
                        {
                            "name": "Checkout",
                            "uses": "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                            "with": {"fetch-depth": 0},
                        }
                    ]
                }
            }
        }
        violations = find_workflow_credential_violations("mutant-m1.yml", wf)
        self.assertEqual(1, len(violations))
        self.assertIn("persist-credentials: false", violations[0])

    def test_mutant_m2_persist_credentials_true_is_rejected(self) -> None:
        wf = {
            "jobs": {
                "build": {
                    "steps": [
                        {
                            "name": "Checkout",
                            "uses": "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                            "with": {"persist-credentials": True},
                        }
                    ]
                }
            }
        }
        violations = find_workflow_credential_violations("mutant-m2.yml", wf)
        self.assertEqual(1, len(violations))
        self.assertIn("got True", violations[0])

    def test_mutant_m3_unauthenticated_network_git_is_rejected_while_explicit_auth_passes(self) -> None:
        wf_unauth = {
            "jobs": {
                "release": {
                    "steps": [
                        {
                            "name": "Fetch tag",
                            "run": 'git -C plugin fetch --force --no-tags origin "+refs/tags/v1.0:refs/tags/v1.0"',
                        }
                    ]
                }
            }
        }
        violations = find_workflow_credential_violations("mutant-m3.yml", wf_unauth)
        self.assertEqual(1, len(violations))
        self.assertIn("network git command without explicit per-command auth", violations[0])

        wf_auth = {
            "jobs": {
                "release": {
                    "steps": [
                        {
                            "name": "Fetch tag",
                            "env": {"GH_TOKEN": "${{ github.token }}"},
                            "run": (
                                'AUTH_HEADER="$(printf \'x-access-token:%s\' "${GH_TOKEN}" | base64 | tr -d \'\\n\')"\n'
                                'git -C plugin -c "http.https://github.com/.extraheader=AUTHORIZATION: basic ${AUTH_HEADER}" '
                                'fetch --force --no-tags origin "+refs/tags/v1.0:refs/tags/v1.0"'
                            ),
                        }
                    ]
                }
            }
        }
        self.assertEqual([], find_workflow_credential_violations("auth-ok.yml", wf_auth))

    def test_mutant_m3_command_substitution_git_is_rejected(self) -> None:
        wf = {
            "jobs": {
                "release": {
                    "steps": [
                        {
                            "name": "Inspect remote tag",
                            "run": 'REMOTE_SHA="$(git -C plugin ls-remote origin refs/tags/v1.0)"',
                        }
                    ]
                }
            }
        }
        violations = find_workflow_credential_violations("mutant-m3-cmdsub.yml", wf)
        self.assertEqual(1, len(violations))
        self.assertIn("network git command without explicit per-command auth", violations[0])

    def test_mutant_m4_line_continuation_git_fetch_is_rejected(self) -> None:
        wf = {
            "jobs": {
                "release": {
                    "steps": [
                        {
                            "name": "Fetch tag multiline",
                            "run": 'git -C plugin \\\n  fetch --force origin "+refs/tags/v1.0:refs/tags/v1.0"',
                        }
                    ]
                }
            }
        }
        violations = find_workflow_credential_violations("mutant-m4-multiline.yml", wf)
        self.assertEqual(1, len(violations))
        self.assertIn("network git command without explicit per-command auth", violations[0])

        wf_multiline_auth = {
            "jobs": {
                "release": {
                    "steps": [
                        {
                            "name": "Fetch tag multiline with auth",
                            "env": {"GH_TOKEN": "${{ github.token }}"},
                            "run": (
                                'git -C plugin \\\n'
                                '  -c "http.https://github.com/.extraheader=AUTHORIZATION: basic ${AUTH_HEADER}" \\\n'
                                '  fetch --force origin "+refs/tags/v1.0:refs/tags/v1.0"'
                            ),
                        }
                    ]
                }
            }
        }
        self.assertEqual([], find_workflow_credential_violations("multiline-auth-ok.yml", wf_multiline_auth))

    def test_mutant_m6_conditional_if_git_ls_remote_is_rejected(self) -> None:
        wf = {
            "jobs": {
                "release": {
                    "steps": [
                        {
                            "name": "Check remote ref",
                            "run": "if git ls-remote --exit-code origin refs/tags/v1.0; then echo exists; fi",
                        }
                    ]
                }
            }
        }
        violations = find_workflow_credential_violations("mutant-m6-if.yml", wf)
        self.assertEqual(1, len(violations))
        self.assertIn("network git command without explicit per-command auth", violations[0])


if __name__ == "__main__":
    unittest.main()
