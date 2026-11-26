"""Contrato de aislamiento de secretos y caché en workflows (TAREA-587.14, r8 del fusionador).

1. Jobs de pruebas (`tests.yml`, salvo `coverage-upload`):
   - Todo `actions/checkout` con `persist-credentials: false` (incluido cualquier `ssh-key:`).
   - Ningún `secrets.*` ni `github.token` en `env` (workflow, job o paso) ni en `run`.
   - `permissions` explícitos de solo lectura (`contents: read`), sin ningún `write` ni `id-token`.
   - Ninguna acción que pueda usar caché: solo `actions/checkout`, `actions/upload-artifact`,
     `actions/download-artifact`, `shivammathur/setup-php`, y `actions/setup-node` con
     `package-manager-cache: false` y sin `cache:`.
2. Ningún workflow del repo (`tests.yml`, `release.yml`, `promote-prod.yml`, reutilizables)
   restaura caché: sin `actions/cache` y todo `actions/setup-node` con
   `package-manager-cache: false` y sin `cache:`.
3. `coverage-upload`:
   - Sin checkout del plugin.
   - Solo `actions/download-artifact@<sha40>` y acciones de terceros fijadas a SHA de 40
     (`codecov/codecov-action@<sha40>`).
   - No ejecuta ni importa nada del artefacto; no toca la caché.
   - Los secretos (`CODECOV_TOKEN`, `CI_EVIDENCE_S3_*`) viven solo ahí, con
     `permissions: contents: read`.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github/workflows"
WORKFLOW = WORKFLOWS_DIR / "tests.yml"
TEMPLATE_SYNC = ROOT / ".beply/template-sync.json"

SHA40_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")
DOT_SECRET_RE = re.compile(r"\bsecrets\.[A-Za-z0-9_]+\b")
GITHUB_TOKEN_RE = re.compile(r"\bgithub\.token\b")
UPLOAD_ONLY_SECRETS_RE = re.compile(r"\b(?:CODECOV_TOKEN|CI_EVIDENCE_S3_[A-Za-z0-9_]+)\b")
ALLOWED_TEST_JOB_ACTIONS = {
    "actions/checkout",
    "actions/upload-artifact",
    "actions/download-artifact",
    "shivammathur/setup-php",
    "actions/setup-node",
}
FORBIDDEN_EXEC_RE = re.compile(
    r"(?:"
    r"\b(?:bash|sh|zsh|dash|php|node|python3?)\b"
    r"|\bpython3?\s+-[mc]\b"
    r"|\bnode\s+-e\b"
    r"|\bphp\s+-r\b"
    r"|\bimport\b"
    r"|\brequire\s*\("
    r"|\brequire(?:_once)?\b"
    r"|\binclude(?:_once)?\b"
    r"|\bsource\b"
    r"|\beval\b"
    r")",
    re.IGNORECASE,
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def iter_env_values(mapping: dict | None):
    if not isinstance(mapping, dict):
        return
    for key, value in mapping.items():
        yield str(key), str(value)


def action_slug(uses: str) -> str:
    return uses.split("@", 1)[0].strip()


class TestsSecretsIsolationContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_yaml(WORKFLOW)
        self.jobs = self.workflow["jobs"]

    def _assert_readonly_permissions(self, perms, label: str):
        self.assertIsInstance(perms, dict, f"{label} must declare explicit permissions mapping")
        self.assertEqual(perms.get("contents"), "read", f"{label} must declare contents: read")
        self.assertNotIn("id-token", perms, f"{label} must not declare id-token permission")
        for scope, level in perms.items():
            self.assertNotEqual(level, "write", f"{label} permission {scope} must not be write")
            self.assertIn(level, ("read", "none"), f"{label} permission {scope}={level!r} must be read or none")

    def test_workflow_and_jobs_have_explicit_readonly_permissions_and_no_id_token(self):
        self._assert_readonly_permissions(self.workflow.get("permissions"), "tests.yml workflow")
        for job_name, job in self.jobs.items():
            with self.subTest(job=job_name):
                self._assert_readonly_permissions(job.get("permissions"), f"tests.yml job {job_name}")

    def test_workflow_env_has_no_secrets_or_github_token(self):
        for key, value in iter_env_values(self.workflow.get("env")):
            with self.subTest(env_key=key):
                self.assertIsNone(DOT_SECRET_RE.search(value), f"workflow env.{key} references a secret")
                self.assertIsNone(GITHUB_TOKEN_RE.search(value), f"workflow env.{key} references github.token")

    def test_test_jobs_have_no_dot_secrets_or_github_token_in_env_or_run(self):
        test_jobs = {name: job for name, job in self.jobs.items() if name != "coverage-upload"}
        self.assertTrue(test_jobs, "tests.yml must define test jobs")
        for job_name, job in test_jobs.items():
            for key, value in iter_env_values(job.get("env")):
                with self.subTest(job=job_name, job_env=key):
                    self.assertIsNone(DOT_SECRET_RE.search(value), f"{job_name}.env.{key} must not use secrets.*")
                    self.assertIsNone(GITHUB_TOKEN_RE.search(value), f"{job_name}.env.{key} must not use github.token")
            for idx, step in enumerate(job.get("steps", [])):
                step_label = step.get("name", f"step[{idx}]")
                for key, value in iter_env_values(step.get("env")):
                    with self.subTest(job=job_name, step=step_label, env_key=key):
                        self.assertIsNone(
                            DOT_SECRET_RE.search(value),
                            f"{job_name} / {step_label} env.{key} must not reference secrets.*",
                        )
                        self.assertIsNone(
                            GITHUB_TOKEN_RE.search(value),
                            f"{job_name} / {step_label} env.{key} must not reference github.token",
                        )
                run_cmd = str(step.get("run", ""))
                with self.subTest(job=job_name, step=step_label, field="run"):
                    self.assertIsNone(
                        DOT_SECRET_RE.search(run_cmd),
                        f"{job_name} / {step_label} run must not reference secrets.*",
                    )
                    self.assertIsNone(
                        GITHUB_TOKEN_RE.search(run_cmd),
                        f"{job_name} / {step_label} run must not reference github.token",
                    )

    def test_test_jobs_only_use_allowed_non_caching_actions_and_disable_persist_credentials(self):
        for job_name, job in self.jobs.items():
            if job_name == "coverage-upload":
                continue
            for idx, step in enumerate(job.get("steps", [])):
                uses = str(step.get("uses", ""))
                if not uses:
                    continue
                step_label = step.get("name", f"step[{idx}]")
                slug = action_slug(uses)
                with self.subTest(job=job_name, step=step_label):
                    self.assertRegex(uses, SHA40_RE, f"{job_name}: action {uses} must be pinned to 40-hex SHA")
                    self.assertIn(
                        slug,
                        ALLOWED_TEST_JOB_ACTIONS,
                        f"{job_name} / {step_label} uses disallowed/cache-capable action {slug}",
                    )
                    with_cfg = step.get("with") or {}
                    if slug == "actions/checkout":
                        self.assertIs(
                            with_cfg.get("persist-credentials"),
                            False,
                            f"{job_name} / {step_label} must set persist-credentials: false",
                        )
                    if slug == "actions/setup-node":
                        self.assertIs(
                            with_cfg.get("package-manager-cache"),
                            False,
                            f"{job_name} / {step_label} must set package-manager-cache: false",
                        )
                        self.assertNotIn("cache", with_cfg, f"{job_name} / {step_label} must not set cache:")

    def test_no_workflow_in_repo_restores_cache_or_enables_setup_node_cache(self):
        for wf_path in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
            doc = load_yaml(wf_path)
            for job_name, job in (doc.get("jobs") or {}).items():
                for idx, step in enumerate(job.get("steps") or []):
                    uses = str(step.get("uses", ""))
                    if not uses:
                        continue
                    slug = action_slug(uses)
                    with self.subTest(workflow=wf_path.name, job=job_name, step=step.get("name", f"step[{idx}]")):
                        self.assertFalse(
                            slug.startswith("actions/cache"),
                            f"{wf_path.name}:{job_name} must not use actions/cache",
                        )
                        if slug == "actions/setup-node":
                            with_cfg = step.get("with") or {}
                            self.assertIs(
                                with_cfg.get("package-manager-cache"),
                                False,
                                f"{wf_path.name}:{job_name} setup-node must set package-manager-cache: false",
                            )
                            self.assertNotIn(
                                "cache",
                                with_cfg,
                                f"{wf_path.name}:{job_name} setup-node must not set cache:",
                            )

    def test_coverage_upload_job_exists_with_read_permissions_no_checkout_and_no_cache(self):
        self.assertIn("coverage-upload", self.jobs, "tests.yml must define a dedicated coverage-upload job")
        job = self.jobs["coverage-upload"]
        self._assert_readonly_permissions(job.get("permissions"), "coverage-upload")
        needs = job.get("needs")
        needs_list = [needs] if isinstance(needs, str) else list(needs or [])
        self.assertIn("unit", needs_list, "coverage-upload must depend on unit")

        steps = job.get("steps", [])
        self.assertTrue(steps, "coverage-upload must have steps")
        saw_download = False
        saw_codecov = False
        for idx, step in enumerate(steps):
            step_label = step.get("name", f"step[{idx}]")
            uses = str(step.get("uses", ""))
            with self.subTest(step=step_label):
                self.assertFalse(
                    uses.startswith("actions/checkout"),
                    "coverage-upload must NOT checkout the plugin repository",
                )
                self.assertFalse(
                    uses.startswith("actions/cache"),
                    "coverage-upload must NOT touch cache",
                )
                if uses:
                    self.assertRegex(uses, SHA40_RE, f"coverage-upload step {step_label} must pin a 40-hex SHA")
                    if uses.startswith("actions/download-artifact@"):
                        saw_download = True
                    if uses.startswith("codecov/codecov-action@"):
                        saw_codecov = True
                if "run" in step:
                    run_cmd = str(step["run"])
                    self.assertIsNone(
                        FORBIDDEN_EXEC_RE.search(run_cmd),
                        f"coverage-upload step {step_label} must only treat downloaded files as data",
                    )
        self.assertTrue(saw_download, "coverage-upload must download the coverage artifact")
        self.assertTrue(saw_codecov, "coverage-upload must upload coverage via pinned codecov/codecov-action")

    def test_coverage_and_s3_secrets_appear_only_in_coverage_upload(self):
        for job_name, job in self.jobs.items():
            if job_name == "coverage-upload":
                continue
            serialized = yaml.safe_dump(job)
            with self.subTest(job=job_name):
                self.assertIsNone(
                    UPLOAD_ONLY_SECRETS_RE.search(serialized),
                    f"{job_name} must not reference CODECOV_TOKEN or CI_EVIDENCE_S3_*",
                )
        upload_serialized = yaml.safe_dump(self.jobs["coverage-upload"])
        self.assertIn("CODECOV_TOKEN", upload_serialized)

    def test_template_sync_overwrites_tests_and_isolation_test(self):
        ini = (ROOT / "facturascripts.ini").read_text(encoding="utf-8")
        if not re.search(r"^name\s*=\s*['\"]?BeplyPluginTemplate['\"]?\s*$", ini, re.MULTILINE):
            return
        policy = json.loads(TEMPLATE_SYNC.read_text(encoding="utf-8"))
        self.assertIn(".github/workflows/tests.yml", policy.get("overwrite", []))
        self.assertIn("scripts/ci/test_tests_secrets_isolation.py", policy.get("overwrite", []))


if __name__ == "__main__":
    unittest.main()
