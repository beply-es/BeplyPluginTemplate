from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import yaml

from scripts.ci.build_plugin_zip import BuildError, build_plugin_zip
from scripts.ci.immutable_plugin_contract import (
    ContractError,
    parse_dev100_evidence_log,
    validate_immutable_identity,
)


EXPECTED = {
    "schemaVersion": "beply.plugin.dev100.v1",
    "pluginName": "BeplyCRM",
    "version": "16.3",
    "versionId": "11111111-1111-4111-8111-111111111111",
    "checksum": "sha256:" + ("a" * 64),
    "fileSize": 4242,
    "releaseTag": "v16.3",
    "sourceSha": "b" * 40,
}

EXPECTED_CALENDAR = {
    **EXPECTED,
    "pluginName": "CalendarioCitas",
    "version": "7.1",
    "versionId": "22222222-2222-4222-8222-222222222222",
    "checksum": "sha256:" + ("c" * 64),
    "fileSize": 1206000,
    "releaseTag": "v7.1",
    "sourceSha": "d" * 40,
}


class ImmutableIdentityTests(unittest.TestCase):
    def test_accepts_exact_canonical_identity(self) -> None:
        self.assertEqual(validate_immutable_identity(EXPECTED), EXPECTED)

    def test_rejects_ambiguous_or_malformed_identity(self) -> None:
        for field, value in (
            ("version", "latest"),
            ("versionId", "version-latest"),
            ("checksum", "sha256:latest"),
            ("fileSize", 0),
            ("releaseTag", "main"),
            ("sourceSha", "HEAD"),
        ):
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_immutable_identity({**EXPECTED, field: value})

    def test_parses_one_machine_readable_dev100_record_from_prefixed_logs(self) -> None:
        record = json.dumps(EXPECTED, separators=(",", ":"), sort_keys=True)
        log = (
            "job\tstep\t2026-08-03T00:00:00Z prelude\n"
            f"job\tstep\tBEPLY_PLUGIN_DEV100_EVIDENCE_JSON={record}\n"
        )

        self.assertEqual(parse_dev100_evidence_log(log, EXPECTED), EXPECTED)

    def test_ignores_unexpanded_actions_script_source_before_runtime_record(self) -> None:
        record = json.dumps(EXPECTED, separators=(",", ":"), sort_keys=True)
        log = (
            "job\tstep\tMARKER_NAME='BEPLY_PLUGIN_DEV100_EVIDENCE_JSON'\n"
            "job\tstep\tprintf '%s=%s\\n' \"${MARKER_NAME}\" \"${EVIDENCE}\"\n"
            f"job\tstep\tBEPLY_PLUGIN_DEV100_EVIDENCE_JSON={record}\n"
        )

        self.assertEqual(parse_dev100_evidence_log(log, EXPECTED), EXPECTED)

    def test_rejects_missing_duplicate_extra_or_drifted_dev100_records(self) -> None:
        canonical = json.dumps(EXPECTED, separators=(",", ":"), sort_keys=True)
        cases = {
            "missing": "no evidence",
            "duplicate": (
                f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={canonical}\n"
                f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={canonical}\n"
            ),
            "extra": "BEPLY_PLUGIN_DEV100_EVIDENCE_JSON="
            + json.dumps({**EXPECTED, "unsafe": "value"}),
            "drift": "BEPLY_PLUGIN_DEV100_EVIDENCE_JSON="
            + json.dumps({**EXPECTED, "fileSize": 4243}),
        }
        for name, log in cases.items():
            with self.subTest(name=name), self.assertRaises(ContractError):
                parse_dev100_evidence_log(log, EXPECTED)

    def test_opt_in_selects_one_exact_plugin_from_a_multi_plugin_fullset_log(self) -> None:
        crm = json.dumps(EXPECTED, separators=(",", ":"), sort_keys=True)
        calendar = json.dumps(
            EXPECTED_CALENDAR,
            separators=(",", ":"),
            sort_keys=True,
        )
        log = (
            f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={crm}\n"
            f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={calendar}\n"
        )

        with self.assertRaisesRegex(ContractError, "exactly one"):
            parse_dev100_evidence_log(log, EXPECTED_CALENDAR)
        self.assertEqual(
            parse_dev100_evidence_log(
                log,
                EXPECTED_CALENDAR,
                allow_other_plugin_records=True,
            ),
            EXPECTED_CALENDAR,
        )

    def test_multi_plugin_opt_in_rejects_duplicate_target_or_invalid_peer(self) -> None:
        calendar = json.dumps(
            EXPECTED_CALENDAR,
            separators=(",", ":"),
            sort_keys=True,
        )
        duplicate = (
            f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={calendar}\n"
            f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={calendar}\n"
        )
        invalid_peer = json.dumps({**EXPECTED, "unsafe": "value"})

        for log in (
            duplicate,
            f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={invalid_peer}\n"
            f"BEPLY_PLUGIN_DEV100_EVIDENCE_JSON={calendar}\n",
        ):
            with self.subTest(log=log), self.assertRaises(ContractError):
                parse_dev100_evidence_log(
                    log,
                    EXPECTED_CALENDAR,
                    allow_other_plugin_records=True,
                )

    def test_reusable_promotion_exposes_fail_closed_multi_plugin_opt_in(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-promote-immutable-plugin-candidate.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("allow_other_plugin_evidence:", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("ALLOW_OTHER_PLUGIN_EVIDENCE", workflow)
        self.assertIn("--allow-other-plugin-records", workflow)

    def test_reusable_promotion_retains_builtin_github_token_fallback(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-promote-immutable-plugin-candidate.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "BEPLY_PROMOTION_GITHUB_TOKEN:\n        required: false",
            workflow,
        )
        self.assertIn(
            "GH_TOKEN: ${{ secrets.BEPLY_PROMOTION_GITHUB_TOKEN || github.token }}",
            workflow,
        )

    def test_reusable_promotion_preserves_explicit_historical_provenance(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-promote-immutable-plugin-candidate.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("source_repo_full_name:", workflow)
        self.assertIn("source_release_url:", workflow)
        self.assertIn("source_published_at:", workflow)
        self.assertIn(
            "SOURCE_REPO_FULL_NAME: ${{ inputs.source_repo_full_name || github.repository }}",
            workflow,
        )
        self.assertIn('--repo "${SOURCE_REPO_FULL_NAME}"', workflow)
        self.assertIn('-F "sourceRepoFullName=${SOURCE_REPO_FULL_NAME}"', workflow)
        self.assertIn('-F "sourceReleaseUrl=${SOURCE_RELEASE_URL}"', workflow)
        self.assertIn('-F "sourcePublishedAt=${SOURCE_PUBLISHED_AT}"', workflow)
        self.assertIn("source_published_at does not match GitHub Release", workflow)
        self.assertIn(
            "source repo and release URL overrides must be supplied together",
            workflow,
        )
        self.assertIn("source release URL mismatch", workflow)
        self.assertNotIn('-F "sourceRepoFullName=${GITHUB_REPOSITORY}"', workflow)

    def test_release_metadata_uses_the_asset_repository_read_identity(self) -> None:
        path = Path(__file__).resolve().parents[2] / ".github/workflows/reusable-promote-immutable-plugin-candidate.yml"
        steps = yaml.safe_load(path.read_text())["jobs"]["promote"]["steps"]
        metadata = next(step for step in steps if step.get("id") == "release_metadata")
        asset = next(step for step in steps if "gh release download" in step.get("run", ""))
        evidence = next(step for step in steps if "RUN_JSON=" in step.get("run", ""))
        self.assertEqual(metadata["env"]["GH_TOKEN"], asset["env"]["GH_TOKEN"])
        self.assertEqual(metadata["env"]["SOURCE_REPO_FULL_NAME"], asset["env"]["SOURCE_REPO_FULL_NAME"])
        self.assertNotEqual(metadata["env"]["GH_TOKEN"], evidence["env"]["GH_TOKEN"])
        self.assertIn("secrets.BEPLY_PROMOTION_GITHUB_TOKEN", evidence["env"]["GH_TOKEN"])

    def test_release_uploads_use_canonical_github_publication_timestamp(self) -> None:
        workflows = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-immutable-plugin-candidate.yml",
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-promote-immutable-plugin-candidate.yml",
        )

        for path in workflows:
            with self.subTest(workflow=path.name):
                workflow = path.read_text(encoding="utf-8")
                self.assertIn("Resolve canonical GitHub Release publication timestamp", workflow)
                self.assertIn(".published_at // empty", workflow)
                self.assertIn('-F "sourcePublishedAt=${SOURCE_PUBLISHED_AT}"', workflow)
                self.assertNotIn("sourcePublishedAt=$(date -u", workflow)
                self.assertNotIn("SOURCE_PUBLISHED_AT_EFFECTIVE", workflow)

    def test_candidate_uploads_accept_initial_plugin_submissions(self) -> None:
        dev_workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-immutable-plugin-candidate.yml"
        ).read_text(encoding="utf-8")
        prod_workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/reusable-promote-immutable-plugin-candidate.yml"
        ).read_text(encoding="utf-8")

        for workflow in (dev_workflow, prod_workflow):
            self.assertIn("plugin_version)", workflow)
            self.assertIn("plugin_submission)", workflow)
            self.assertIn("submission_id=${SUBMISSION_ID}", workflow)
        self.assertIn("beply.plugin.submission-candidate.v1", dev_workflow)
        self.assertIn("beply.plugin.prod-submission-candidate.v1", prod_workflow)


class DeterministicPluginZipTests(unittest.TestCase):
    def test_builds_one_deterministic_payload_without_tooling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            (root / "facturascripts.ini").write_text(
                "name = BeplyDemo\nversion = 1.2\n",
                encoding="utf-8",
            )
            (root / "Init.php").write_text("<?php\n", encoding="utf-8")
            (root / "run-tests.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (root / ".github").mkdir()
            (root / ".github/workflow.yml").write_text("secret tooling", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs/internal.md").write_text("internal", encoding="utf-8")
            output = Path(tmp) / "candidate.zip"

            first = build_plugin_zip(root, output, "BeplyDemo", "1.2")
            os.utime(root / "Init.php", (1_900_000_000, 1_900_000_000))
            second = build_plugin_zip(root, output, "BeplyDemo", "1.2")

            self.assertEqual(first, second)
            self.assertRegex(first["checksum"], r"^sha256:[0-9a-f]{64}$")
            self.assertGreater(first["fileSize"], 0)
            with ZipFile(output) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["BeplyDemo/Init.php", "BeplyDemo/facturascripts.ini"],
                )

    def test_attestation_matches_backend_canonical_sbom_without_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            (root / "facturascripts.ini").write_text(
                "name = BeplyDemo\nversion = 1.2\n",
                encoding="utf-8",
            )
            (root / "Init.php").write_text("<?php\n", encoding="utf-8")
            zip_path = Path(tmp) / "BeplyDemo-v1.2.zip"
            built = build_plugin_zip(root, zip_path, "BeplyDemo", "1.2")
            output_path = Path(tmp) / "outputs"
            environment = {
                **os.environ,
                "PLUGIN_NAME": "BeplyDemo",
                "PLUGIN_VERSION": "1.2",
                "PLUGIN_ZIP": str(zip_path),
                "PLUGIN_RELEASE_TRACK": "main",
                "PLUGIN_ARTIFACT_PREFIX": "plugins/dev",
                "SOURCE_REPO_FULL_NAME": "beply-es/BeplyDemo",
                "SOURCE_RELEASE_TAG": "v1.2",
                "SOURCE_RELEASE_URL": "https://github.com/beply-es/BeplyDemo/releases/tag/v1.2",
                "SOURCE_SHA": "b" * 40,
                "GITHUB_OUTPUT": str(output_path),
            }

            subprocess.run(
                ["node", "scripts/ci/build_plugin_artifact_attestation.mjs"],
                cwd=Path(__file__).resolve().parents[2],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            outputs = dict(
                line.split("=", 1)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(outputs["artifact_checksum"], built["checksum"])
            self.assertEqual(int(outputs["file_size"]), built["fileSize"])
            self.assertEqual(outputs["has_attestation"], "false")
            sbom = json.loads(Path(outputs["sbom_path"]).read_text(encoding="utf-8"))
            properties = {
                item["name"]: item["value"]
                for item in sbom["metadata"]["component"]["properties"]
            }
            self.assertEqual(
                properties,
                {
                    "beply:releaseTrack": "main",
                    "beply:artifactKey": "plugins/dev/beplydemo/1.2/plugin.zip",
                    "beply:fileSize": str(built["fileSize"]),
                    "beply:sourceRepoFullName": "beply-es/BeplyDemo",
                    "beply:sourceReleaseTag": "v1.2",
                },
            )

    def test_rejects_symlinked_payload_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            (root / "facturascripts.ini").write_text(
                "name = BeplyDemo\nversion = 1.2\n",
                encoding="utf-8",
            )
            (root / "outside").symlink_to(Path(tmp) / "missing")

            with self.assertRaises(BuildError):
                build_plugin_zip(
                    root,
                    Path(tmp) / "candidate.zip",
                    "BeplyDemo",
                    "1.2",
                )


class ReleaseAdapterMigrationTests(unittest.TestCase):
    def _run_validator(self, root: Path) -> subprocess.CompletedProcess[str]:
        workflow_dir = root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        (root / "facturascripts.ini").write_text(
            "name = BeplyDemo\nversion = 1.2\nmin_php = 8.4\n",
            encoding="utf-8",
        )
        (workflow_dir / "tests.yml").write_text(
            "validate-template-contract.mjs\n"
            "validate-docs-impact.mjs\n"
            "v2026.3\nv2026.2\n",
            encoding="utf-8",
        )
        return subprocess.run(
            [
                "node",
                str(Path(__file__).with_name("validate-release-model.mjs")),
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

    def test_legacy_product_adapter_remains_valid_until_opt_in_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow_dir = root / ".github" / "workflows"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "release.yml").write_text(
                "Verify Tests Workflow\n"
                "validate-docs-impact.mjs --require-ai\n"
                "/api/v1/plugins/release\n",
                encoding="utf-8",
            )

            result = self._run_validator(root)

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_opt_in_migration_requires_both_adapters_at_one_exact_sha(self) -> None:
        exact_sha = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow_dir = root / ".github" / "workflows"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "release.yml").write_text(
                "Verify Tests Workflow\n"
                "validate-docs-impact.mjs --require-ai\n"
                "uses: beply-es/BeplyPluginTemplate/.github/workflows/"
                f"reusable-immutable-plugin-candidate.yml@{exact_sha}\n",
                encoding="utf-8",
            )

            half_migrated = self._run_validator(root)
            self.assertNotEqual(half_migrated.returncode, 0)
            self.assertIn("promotion contract", half_migrated.stderr)

            (workflow_dir / "promote-prod.yml").write_text(
                "uses: beply-es/BeplyPluginTemplate/.github/workflows/"
                f"reusable-promote-immutable-plugin-candidate.yml@{exact_sha}\n",
                encoding="utf-8",
            )
            fully_migrated = self._run_validator(root)
            self.assertEqual(fully_migrated.returncode, 0, fully_migrated.stderr)


if __name__ == "__main__":
    unittest.main()


class SourceProvenanceCarrierTests(unittest.TestCase):
    """Estructura que el verificador del backend exige al publicador por tag.

    El backend (raiz `tag-publisher`) lee este reusable en el SHA permitido y
    exige: job interno `source_provenance` con nombre exacto, un unico paso de
    subida `actions/upload-artifact@<sha40>` con el nombre de artefacto literal y
    sin `continue-on-error`; y el job del POST separado con `needs`, para que el
    job publicador ya este `completed/success` cuando el backend lo consulta.
    """

    ROOT = Path(__file__).resolve().parents[2]
    INNER_JOB_KEY = "source_provenance"
    INNER_JOB_NAME = "Publish Immutable Release And Source Provenance Carrier"
    UPLOAD_STEP_NAME = "Upload plugin source provenance carrier"
    ARTIFACT_NAME = "plugin-source-provenance-${{ github.run_id }}-${{ github.run_attempt }}"

    def _candidate(self):
        path = self.ROOT / ".github/workflows/reusable-immutable-plugin-candidate.yml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_inner_publisher_job_uploads_exactly_one_pinned_carrier(self) -> None:
        jobs = self._candidate()["jobs"]
        inner = jobs[self.INNER_JOB_KEY]
        self.assertEqual(inner["name"], self.INNER_JOB_NAME)
        self.assertNotIn("strategy", inner)
        self.assertNotIn("continue-on-error", inner)
        self.assertEqual(inner["permissions"].get("actions"), "read")
        uploads = [step for step in inner["steps"] if step.get("name") == self.UPLOAD_STEP_NAME]
        self.assertEqual(len(uploads), 1)
        upload = uploads[0]
        self.assertRegex(upload["uses"], r"^actions/upload-artifact@[0-9a-f]{40}$")
        self.assertEqual(upload["with"]["name"], self.ARTIFACT_NAME)
        self.assertEqual(upload["with"].get("if-no-files-found"), "error")
        self.assertNotIn("continue-on-error", upload)
        self.assertNotIn("if", upload)
        self.assertEqual(inner["outputs"]["artifact_id"], "${{ steps.provenance_carrier.outputs.artifact-id }}")
        self.assertEqual(upload.get("id"), "provenance_carrier")

    def test_manifest_builder_knows_its_own_inner_job_and_tag_peel_is_enforced(self) -> None:
        inner = self._candidate()["jobs"][self.INNER_JOB_KEY]
        steps = inner["steps"]
        names = [step.get("name") for step in steps]
        builder = next(step for step in steps if "build_source_provenance_manifest.mjs" in (step.get("run") or ""))
        self.assertEqual(builder["env"]["PUBLISHER_JOB_NAME"], self.INNER_JOB_NAME)
        self.assertEqual(builder["env"]["CALLER_JOB_KEY"], "${{ inputs.caller_job_key }}")
        self.assertLess(names.index(builder["name"]), names.index(self.UPLOAD_STEP_NAME))
        peel = next(step for step in steps if "^{commit}" in (step.get("run") or ""))
        self.assertIn('refs/tags/${GITHUB_REF_NAME}^{commit}', peel["run"])
        self.assertIn('"${GITHUB_SHA}"', peel["run"])
        self.assertLess(names.index(peel["name"]), names.index("Create immutable GitHub Release asset"))
        self.assertEqual(
            sum("build_plugin_zip.py" in (step.get("run") or "") for job in self._candidate()["jobs"].values() for step in job["steps"]),
            1,
        )

    def test_post_job_needs_the_carrier_job_and_sends_the_locator(self) -> None:
        doc = self._candidate()
        publish = doc["jobs"]["publish"]
        self.assertEqual(publish["needs"], self.INNER_JOB_KEY)
        upload_dev = next(step for step in publish["steps"] if step.get("id") == "upload_dev")
        body = upload_dev["run"]
        self.assertIn('--form-string "sourceProvenance=${SOURCE_PROVENANCE_LOCATOR}"', body)
        self.assertIn('-F "sourceProvenanceEnvironment=${SOURCE_PROVENANCE_ENVIRONMENT}"', body)
        self.assertIn('-F "sourceBranch=${GITHUB_REF_NAME}"', body)
        self.assertIn('-F "releaseTrack=${RELEASE_TRACK}"', body)
        self.assertIn("manifestArtifactId:$manifestArtifactId", body)
        env = upload_dev["env"]
        self.assertEqual(env["MANIFEST_ARTIFACT_ID"], "${{ needs.source_provenance.outputs.artifact_id }}")
        self.assertEqual(env["PUBLISHER_JOB_ID"], "${{ needs.source_provenance.outputs.publisher_job_id }}")
        inputs = doc[True]["workflow_call"]["inputs"] if True in doc else doc["on"]["workflow_call"]["inputs"]
        self.assertEqual(inputs["source_provenance_environment"]["default"], "dev")
        self.assertIs(inputs["submit_source_provenance"]["default"], True)
        self.assertEqual(inputs["caller_job_key"]["default"], "publish_immutable_candidate")
        self.assertNotIn("BEPLY_DEV_CI_TOKEN", str(doc["jobs"][self.INNER_JOB_KEY]))

    def test_template_release_never_claims_tag_publisher_provenance_for_a_local_call(self) -> None:
        release = yaml.safe_load((self.ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
        job = release["jobs"]["publish_immutable_candidate"]
        self.assertTrue(job["uses"].startswith("./"))
        self.assertIs(job["with"]["submit_source_provenance"], False)


class ReusableWorkflowToolingTests(unittest.TestCase):
    """El runner `arc-runner-set` NO trae `gh` preinstalado.

    La promocion fallaba con `gh: command not found` (exit 127) en
    `Validate exact DEV100 run`. No era una regresion: ese paso nunca se habia
    alcanzado porque la promocion moria antes. Este guardarrail impide que
    vuelva a colarse un workflow que invoque una herramienta que el runner no
    garantiza.

    Se comprueba la relacion —si se usa, se instala antes— y no un literal, para
    que no caduque al cambiar de version de la CLI.
    """

    WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

    def _reusable_workflows(self):
        return sorted(self.WORKFLOWS.glob("reusable-*.yml"))

    def test_every_workflow_that_uses_gh_installs_it_first(self) -> None:
        found_any = False
        for path in self._reusable_workflows():
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job_name, job in (doc.get("jobs") or {}).items():
                steps = job.get("steps") or []
                installed_at = None
                for index, step in enumerate(steps):
                    body = step.get("run") or ""
                    if "cli/cli/releases/download" in body:
                        installed_at = index if installed_at is None else installed_at
                    uses_gh = re.search(r"(^|[;&|(\s])gh\s+\w", body, re.MULTILINE)
                    if not uses_gh:
                        continue
                    found_any = True
                    self.assertIsNotNone(
                        installed_at,
                        f"{path.name}:{job_name} paso '{step.get('name')}' usa `gh` "
                        "sin que ningun paso anterior lo instale; el runner no lo trae",
                    )
        self.assertTrue(found_any, "ningun workflow reusable usa gh: el test no vigila nada")

    def test_gh_download_is_pinned_and_checksum_verified(self) -> None:
        for path in self._reusable_workflows():
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job in (doc.get("jobs") or {}).values():
                for step in job.get("steps") or []:
                    body = step.get("run") or ""
                    if "cli/cli/releases/download" not in body:
                        continue
                    env = step.get("env") or {}
                    self.assertIn("GH_CLI_VERSION", env, f"{path.name}: version de gh sin pinear")
                    self.assertRegex(
                        str(env.get("GH_CLI_SHA256", "")),
                        r"^[0-9a-f]{64}$",
                        f"{path.name}: descarga de gh sin SHA-256 de 64 hex",
                    )
                    self.assertIn(
                        "sha256sum -c",
                        body,
                        f"{path.name}: se declara SHA-256 pero no se verifica",
                    )
