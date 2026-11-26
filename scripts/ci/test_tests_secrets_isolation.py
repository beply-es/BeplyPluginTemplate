"""Contrato de aislamiento de secretos en tests.yml (TAREA-587.14, r8 del fusionador).

Los jobs que corren pruebas en los plugins no deben recibir secretos ni credenciales
persistidas, para que el fusionador deje de tratar Test/ como arnés de CI:
1. Ningún job de pruebas usa `secrets.<NOMBRE>` ni `github.token` en `env` (workflow,
   job o paso) ni en `run`; todo `actions/checkout` lleva `persist-credentials: false`
   (incluido cualquier checkout con `ssh-key:`).
2. `coverage-upload` NO hace checkout del plugin. Sus pasos son solo
   `actions/download-artifact@<sha40>`, acciones de terceros fijadas a SHA de 40
   (`codecov/codecov-action@<sha40>`) y, si existieran, `run` que tratan los ficheros
   solo como datos (`curl`, `aws s3 cp`, `sha256sum`).
3. En `coverage-upload` ningún `run` ejecuta nada del artefacto ni carga módulos
   (nada de `bash`/`sh`/`php`/`node`/`python` sobre ficheros descargados, ni
   `python -m`/`-c` con `import`, `node -e` con `require` ni `php -r` con `require`).
4. Los secretos (`CODECOV_TOKEN`, `CI_EVIDENCE_S3_*`) viven solo en `coverage-upload`,
   con `permissions: contents: read`.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/tests.yml"
TEMPLATE_SYNC = ROOT / ".beply/template-sync.json"

SHA40_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")
DOT_SECRET_RE = re.compile(r"\bsecrets\.[A-Za-z0-9_]+\b")
GITHUB_TOKEN_RE = re.compile(r"\bgithub\.token\b")
UPLOAD_ONLY_SECRETS_RE = re.compile(r"\b(?:CODECOV_TOKEN|CI_EVIDENCE_S3_[A-Za-z0-9_]+)\b")
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


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def iter_env_values(mapping: dict | None):
    if not isinstance(mapping, dict):
        return
    for key, value in mapping.items():
        yield str(key), str(value)


class TestsSecretsIsolationContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow()
        self.jobs = self.workflow["jobs"]

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

    def test_every_checkout_in_test_jobs_disables_persist_credentials(self):
        for job_name, job in self.jobs.items():
            if job_name == "coverage-upload":
                continue
            for idx, step in enumerate(job.get("steps", [])):
                uses = str(step.get("uses", ""))
                if uses.startswith("actions/checkout@"):
                    with self.subTest(job=job_name, step=step.get("name", f"step[{idx}]")):
                        self.assertRegex(uses, SHA40_RE, f"{job_name}: checkout must be pinned to 40-hex SHA")
                        with_cfg = step.get("with") or {}
                        self.assertIs(
                            with_cfg.get("persist-credentials"),
                            False,
                            f"{job_name} / {step.get('name')} must set persist-credentials: false",
                        )

    def test_coverage_upload_job_exists_with_read_permissions_and_no_checkout(self):
        self.assertIn("coverage-upload", self.jobs, "tests.yml must define a dedicated coverage-upload job")
        job = self.jobs["coverage-upload"]
        self.assertEqual(
            {"contents": "read"},
            job.get("permissions"),
            "coverage-upload must explicitly declare permissions: contents: read",
        )
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
