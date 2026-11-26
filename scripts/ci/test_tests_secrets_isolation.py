"""Contrato de aislamiento de secretos y caché en workflows (TAREA-587.14, r8 del fusionador).

1. Jobs de pruebas (`tests.yml`, salvo `coverage-upload`):
   - Todo `actions/checkout` con `persist-credentials: false` (incluido cualquier `ssh-key:`).
   - Ningún `secrets.*`, `secrets[...]` ni `github.token` en `env` (workflow, job o paso),
     `run` ni `with`, salvo únicamente:
       * `actions/checkout` -> `with.ssh-key` para las deploy keys de dependencias CI;
       * comprobación booleana `!= ''` en `env` del paso `Check CI dependency keys`.
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
     (`codecov/codecov-action@<sha40>` con `disable_search: true`, `files:` explícito y
     `plugins: noop`).
   - No ejecuta ni importa nada del artefacto; no toca la caché.
   - Los secretos (`CODECOV_TOKEN`, `CI_EVIDENCE_S3_*`) viven solo ahí, con
     `permissions: contents: read`.
"""
from __future__ import annotations

import copy
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
ANY_SECRET_RE = re.compile(r"\bsecrets\b", re.IGNORECASE)
EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
GITHUB_TOKEN_RE = re.compile(
    r"\bgithub\s*(?:\.\s*token\b|\[\s*['\"]token['\"]\s*\])",
    re.IGNORECASE,
)
GITHUB_WHOLE_OBJECT_RE = re.compile(
    r"\bgithub\b(?!\s*\.\s*[A-Za-z_][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)
ALLOWED_DEP_KEY_CHECK_STEP = "Check CI dependency keys"
ALLOWED_DEP_KEY_CHECK_RE = re.compile(
    r"^\$\{\{\s*secrets\[needs\.quality_contract\.outputs\.dep[1-4]_ssh_key_secret\]\s*!=\s*''\s*\}\}$"
)
ALLOWED_DEP_SSH_KEY_RE = re.compile(
    r"^\$\{\{\s*secrets\[needs\.quality_contract\.outputs\.dep[1-4]_ssh_key_secret\]\s*\}\}$"
)
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


def _has_disallowed_github_ref(value: str) -> bool:
    if GITHUB_TOKEN_RE.search(value):
        return True
    for expr in EXPR_RE.findall(value):
        if GITHUB_WHOLE_OBJECT_RE.search(expr):
            return True
    return False


def find_test_jobs_secret_violations(workflow: dict) -> list[str]:
    """Devuelve todas las referencias prohibidas a secrets o github.token/github entero en workflow y jobs de pruebas."""
    violations: list[str] = []
    for key, value in iter_env_values(workflow.get("env")):
        if ANY_SECRET_RE.search(value):
            violations.append(f"workflow.env.{key} references a secret: {value}")
        if _has_disallowed_github_ref(value):
            violations.append(f"workflow.env.{key} references github.token or whole github context: {value}")

    jobs = workflow.get("jobs") or {}
    for job_name, job in jobs.items():
        if job_name == "coverage-upload":
            continue
        for key, value in iter_env_values(job.get("env")):
            if ANY_SECRET_RE.search(value):
                violations.append(f"{job_name}.env.{key} must not reference secrets: {value}")
            if _has_disallowed_github_ref(value):
                violations.append(f"{job_name}.env.{key} must not reference github.token or whole github context: {value}")
        for idx, step in enumerate(job.get("steps") or []):
            step_name = str(step.get("name", ""))
            step_label = step_name or f"step[{idx}]"
            slug = action_slug(str(step.get("uses", "")))

            for key, value in iter_env_values(step.get("env")):
                if _has_disallowed_github_ref(value):
                    violations.append(f"{job_name} / {step_label} env.{key} must not reference github.token or whole github context")
                if ANY_SECRET_RE.search(value):
                    is_allowed_check = (
                        step_name == ALLOWED_DEP_KEY_CHECK_STEP
                        and ALLOWED_DEP_KEY_CHECK_RE.match(value.strip()) is not None
                    )
                    if not is_allowed_check:
                        violations.append(
                            f"{job_name} / {step_label} env.{key} must not reference secrets: {value}"
                        )

            run_cmd = str(step.get("run", ""))
            if ANY_SECRET_RE.search(run_cmd):
                violations.append(f"{job_name} / {step_label} run must not reference secrets")
            if _has_disallowed_github_ref(run_cmd):
                violations.append(f"{job_name} / {step_label} run must not reference github.token or whole github context")

            for key, value in iter_env_values(step.get("with")):
                if _has_disallowed_github_ref(value):
                    violations.append(f"{job_name} / {step_label} with.{key} must not reference github.token or whole github context")
                if ANY_SECRET_RE.search(value):
                    is_allowed_ssh_key = (
                        slug == "actions/checkout"
                        and key == "ssh-key"
                        and ALLOWED_DEP_SSH_KEY_RE.match(value.strip()) is not None
                    )
                    if not is_allowed_ssh_key:
                        violations.append(
                            f"{job_name} / {step_label} with.{key} must not reference secrets: {value}"
                        )
    return violations


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

    def test_test_jobs_and_workflow_have_no_disallowed_secrets_or_github_token(self):
        test_jobs = {name: job for name, job in self.jobs.items() if name != "coverage-upload"}
        self.assertTrue(test_jobs, "tests.yml must define test jobs")
        violations = find_test_jobs_secret_violations(self.workflow)
        self.assertEqual(violations, [], f"Disallowed secret references found: {violations}")

    def test_contract_rejects_bracket_secrets_mutants_in_env_run_and_with(self):
        cases = [
            ("workflow_env_single_quote", lambda wf: wf.setdefault("env", {}).__setitem__("LEAK", "${{ secrets['X'] }}")),
            ("job_env_single_quote", lambda wf: wf["jobs"]["unit"].setdefault("env", {}).__setitem__("LEAK", "${{ secrets['X'] }}")),
            ("step_env_single_quote", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ secrets['X'] }}")),
            ("step_env_double_quote", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", '${{ secrets["X"] }}')),
            ("step_env_check_step_without_bool", lambda wf: wf["jobs"]["unit"]["steps"][2]["env"].__setitem__("LEAK", "${{ secrets['X'] }}")),
            ("step_run_single_quote", lambda wf: wf["jobs"]["unit"]["steps"][-1].__setitem__("run", "echo ${{ secrets['X'] }}")),
            ("step_run_double_quote", lambda wf: wf["jobs"]["unit"]["steps"][-1].__setitem__("run", 'echo ${{ secrets["X"] }}')),
            ("step_run_bool_expression_forbidden", lambda wf: wf["jobs"]["unit"]["steps"][2].__setitem__("run", "echo ${{ secrets[needs.quality_contract.outputs.dep1_ssh_key_secret] != '' }}")),
            ("step_with_non_ssh_key_forbidden", lambda wf: wf["jobs"]["unit"]["steps"][0]["with"].__setitem__("token", "${{ secrets['X'] }}")),
            ("step_env_github_bracket_token", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ github['token'] }}")),
        ]
        for case_name, mutate in cases:
            with self.subTest(mutant=case_name):
                mutated = copy.deepcopy(self.workflow)
                mutate(mutated)
                violations = find_test_jobs_secret_violations(mutated)
                self.assertTrue(
                    violations,
                    f"Mutant {case_name} must be rejected by secret isolation contract",
                )

    def test_contract_rejects_whole_secrets_and_whole_github_mutants(self):
        cases = [
            ("step_env_tojson_secrets", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ toJSON(secrets) }}")),
            ("step_run_tojson_secrets", lambda wf: wf["jobs"]["unit"]["steps"][-1].__setitem__("run", "echo '${{ toJSON(secrets) }}'")),
            ("step_env_bare_secrets", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ secrets }}")),
            ("step_env_tojson_github", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ toJSON(github) }}")),
            ("step_run_tojson_github", lambda wf: wf["jobs"]["unit"]["steps"][-1].__setitem__("run", "echo '${{ toJSON(github) }}'")),
            ("step_env_format_github", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ format('{0}', github) }}")),
            ("step_env_bare_github", lambda wf: wf["jobs"]["unit"]["steps"][0].setdefault("env", {}).__setitem__("LEAK", "${{ github }}")),
            ("step_run_bare_github", lambda wf: wf["jobs"]["unit"]["steps"][-1].__setitem__("run", "echo '${{ github }}'")),
            ("workflow_env_tojson_github", lambda wf: wf.setdefault("env", {}).__setitem__("LEAK", "${{ toJSON(github) }}")),
            ("job_env_tojson_secrets", lambda wf: wf["jobs"]["unit"].setdefault("env", {}).__setitem__("LEAK", "${{ toJSON(secrets) }}")),
            ("step_with_tojson_github", lambda wf: wf["jobs"]["unit"]["steps"][0]["with"].__setitem__("ref", "${{ toJSON(github) }}")),
        ]
        for case_name, mutate in cases:
            with self.subTest(mutant=case_name):
                mutated = copy.deepcopy(self.workflow)
                mutate(mutated)
                violations = find_test_jobs_secret_violations(mutated)
                self.assertTrue(
                    violations,
                    f"Mutant {case_name} must be rejected by secret isolation contract",
                )

    def test_unit_uploads_single_non_colliding_coverage_artifact(self):
        unit_steps = self.jobs["unit"]["steps"]
        upload_steps = [
            step for step in unit_steps
            if action_slug(str(step.get("uses", ""))) == "actions/upload-artifact"
        ]
        self.assertEqual(len(upload_steps), 1, "unit must have exactly one coverage upload-artifact step")
        upload = upload_steps[0]
        self.assertEqual(
            (upload.get("with") or {}).get("name"),
            "${{ env.PLUGIN_FOLDER }}-coverage",
            "unit must upload a single non-colliding coverage artifact name without matrix suffix",
        )
        self.assertIn(
            "fromJSON(needs.quality_contract.outputs.fs_refs)[0]",
            str(upload.get("if", "")),
            "unit coverage upload must be gated to a single matrix leg so coverage.xml never collides",
        )
        download_steps = [
            step for step in self.jobs["coverage-upload"]["steps"]
            if action_slug(str(step.get("uses", ""))) == "actions/download-artifact"
        ]
        self.assertEqual(len(download_steps), 1)
        dl_with = download_steps[0].get("with") or {}
        self.assertEqual(
            dl_with.get("pattern"),
            "${{ env.PLUGIN_FOLDER }}-coverage",
            "coverage-upload download-artifact must match the single exact artifact without wildcard collision",
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
                    with_cfg = step.get("with") or {}
                    if uses.startswith("actions/download-artifact@"):
                        saw_download = True
                        self.assertEqual(
                            with_cfg.get("path"),
                            "coverage-artifacts",
                            "coverage-upload download-artifact must extract into coverage-artifacts",
                        )
                        self.assertIs(
                            with_cfg.get("merge-multiple"),
                            True,
                            "coverage-upload download-artifact must set merge-multiple: true for explicit files path",
                        )
                    if uses.startswith("codecov/codecov-action@"):
                        saw_codecov = True
                        self.assertIs(
                            with_cfg.get("disable_search"),
                            True,
                            "coverage-upload codecov-action must set disable_search: true",
                        )
                        self.assertEqual(
                            with_cfg.get("files"),
                            "coverage-artifacts/coverage.xml",
                            "coverage-upload codecov-action must pass explicit files: coverage-artifacts/coverage.xml",
                        )
                        self.assertEqual(
                            with_cfg.get("plugins"),
                            "noop",
                            "coverage-upload codecov-action must set plugins: noop",
                        )
                        self.assertNotIn(
                            "directory",
                            with_cfg,
                            "coverage-upload codecov-action must not set directory when disable_search: true",
                        )
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
