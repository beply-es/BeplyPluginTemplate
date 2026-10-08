from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
import uuid
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

    def test_prod_promotion_accepts_initial_plugin_submissions(self) -> None:
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
        self.assertIn("beply.plugin.prod-submission-candidate.v1", prod_workflow)
        # A DEV submission has no catalog row to read back: it fails closed
        # (DevCandidateCatalogReadbackTests), so it never emits evidence.
        self.assertNotIn("beply.plugin.submission-candidate.v1", dev_workflow)


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

    def test_every_published_asset_is_byte_compared_with_one_deterministic_build(self) -> None:
        steps = self._candidate()["jobs"][self.INNER_JOB_KEY]["steps"]
        build = next(step for step in steps if "build_plugin_zip.py" in (step.get("run") or ""))
        self.assertNotIn("if", build, "the deterministic build must always run")
        self.assertIn("/tmp/build/", build["run"])
        compare = next(step for step in steps if "cmp " in (step.get("run") or ""))
        self.assertNotIn("if", compare, "every asset, new or reused, is byte-compared")
        self.assertIn("gh release download", compare["run"])
        names = [step.get("name") for step in steps]
        self.assertLess(names.index(compare["name"]), names.index("Build source provenance manifest"))

    def test_provenance_only_dispatch_never_creates_a_release_and_requires_one(self) -> None:
        steps = self._candidate()["jobs"][self.INNER_JOB_KEY]["steps"]
        create = next(step for step in steps if step.get("name") == "Create immutable GitHub Release asset")
        self.assertIn("github.event_name == 'push'", create["if"])
        guard = next(step for step in steps if step.get("name") == "Require a published release for provenance-only dispatch")
        self.assertIn("workflow_dispatch", guard["if"])
        validate = next(step for step in steps if step.get("name") == "Validate immutable caller and contract identities")
        self.assertIn("workflow_dispatch", validate["run"])
        self.assertIn('test "${GITHUB_REF_TYPE}" = "tag"', validate["run"])

    def test_template_release_never_claims_tag_publisher_provenance_for_a_local_call(self) -> None:
        release = yaml.safe_load((self.ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
        job = release["jobs"]["publish_immutable_candidate"]
        self.assertTrue(job["uses"].startswith("./"))
        self.assertIs(job["with"]["submit_source_provenance"], False)


class DevCandidateCatalogReadbackTests(unittest.TestCase):
    """La respuesta del POST es el emisor hablando de si mismo, no el catalogo.

    `upload_dev` solo puede salir en verde si, en el mismo paso, lee de vuelta
    del catalogo DEV exactamente una fila `pending_review` para los bytes
    enviados y la identidad que devolvio la subida. Antes, `catalog_identity`
    rechaza sin subir nada un plugin que el catalogo DEV no conoce: su primera
    subida crearia una submission y fallaria despues, un efecto parcial que un
    reintento no arregla (la version es inmutable). Se ejecutan los cuerpos
    reales de los dos pasos, en el orden del job, con `curl` y `gh` sustituidos
    por fixtures; jq, sha256sum y stat son reales.
    """

    ROOT = Path(__file__).resolve().parents[2]
    REPOSITORY = "beply-es/ReadbackFixture"
    TAG = "v1.0"
    VERSION = "1.0"
    PLUGIN_ID = "33333333-3333-4333-8333-333333333333"
    VERSION_ID = "44444444-4444-4444-8444-444444444444"
    SUBMISSION_ID = "55555555-5555-4555-8555-555555555555"
    NEW_PLUGIN = "plugin nuevo: el alta va por la ingesta canónica de k3s, dev/prod-plugin-artifact-ingest.yml"
    FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_CALLS"
if [ "$GH_EXIT" != "0" ]; then
  echo "gh: HTTP 502" >&2
  exit 1
fi
cat "$RELEASES_FILE"
"""
    FAKE_CURL = """#!/bin/sh
case "$*" in
  *release-witness*)
    printf '%s\\n' "$*" >> "$WITNESS_CALLS"
    out=""
    previous=""
    for arg in "$@"; do
      if [ "$previous" = "-o" ]; then out="$arg"; fi
      previous="$arg"
    done
    cat "$WITNESS_FILE" > "$out"
    printf '%s' "$WITNESS_CODE"
    exit 0
    ;;
esac
printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
  *"-X POST"*)
    cat "$POST_BODY_FILE"
    printf '\\n%s' "$POST_CODE"
    ;;
  *)
    if [ "$GET_CODE" != "200" ]; then
      echo "curl: (22) The requested URL returned error: $GET_CODE" >&2
      exit 22
    fi
    cat "$PENDING_FILE"
    ;;
esac
"""

    def _step(self, step_id: str = "upload_dev"):
        path = self.ROOT / ".github/workflows/reusable-immutable-plugin-candidate.yml"
        publish = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["publish"]
        return publish, next(step for step in publish["steps"] if step.get("id") == step_id)

    def _script(self, attested_checksum: str) -> str:
        values = {
            "steps.attestation.outputs.artifact_checksum": attested_checksum,
            "steps.attestation.outputs.artifact_signature": "fixture-signature",
            "steps.attestation.outputs.artifact_signature_key_id": "fixture-key",
            "steps.attestation.outputs.sbom_url": "plugins/dev/fixture.sbom.json",
            "steps.attestation.outputs.sbom_checksum": "sha256:" + "f" * 64,
            "steps.attestation.outputs.artifact_policy_version": "fixture-policy",
        }

        def render(match: re.Match) -> str:
            self.assertIn(match.group(1), values, "unrendered workflow expression in upload_dev")
            return values[match.group(1)]

        return re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", render, self._step()[1]["run"])

    def _run(self, rows=None, *, kind="plugin_version", post_code="201", get_code="200",
             pending=None, checksum=None, file_size=None, attestation="false", provenance="false",
             releases=None, witness_code="200", witness=None, witness_changes=None, gh_exit="0",
             token="fixture-token"):
        name = "ReadbackFixture" + uuid.uuid4().hex[:12]
        payload = b"PK\x03\x04 immutable fixture bytes"
        asset = Path("/tmp") / f"{name}-v{self.VERSION}.zip"
        asset.write_bytes(payload)
        self.addCleanup(asset.unlink, missing_ok=True)
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        directory = Path(scratch.name)
        for tool, body in (("curl", self.FAKE_CURL), ("gh", self.FAKE_GH)):
            (directory / tool).write_text(body)
            (directory / tool).chmod(0o700)
        if releases is None:
            releases = [{"tag_name": self.TAG, "draft": False}, {"tag_name": "v0.9", "draft": False}]
        (directory / "releases.json").write_text(json.dumps(releases))
        if witness is None:
            witness = {"success": True, "data": {"witness": {
                "claimed": True, "pluginId": self.PLUGIN_ID, "versionId": "66666666-6666-4666-8666-666666666666",
                "pluginSlug": name.lower(), "pluginFsName": name, "version": "0.9", "releaseStatus": "approved",
                **(witness_changes or {})}}}
        (directory / "witness.json").write_text(witness if isinstance(witness, str) else json.dumps(witness))
        exact = {
            "versionId": self.VERSION_ID,
            "pluginId": self.PLUGIN_ID,
            "pluginSlug": name.lower(),
            "version": self.VERSION,
            "sourceRepoFullName": self.REPOSITORY,
            "sourceReleaseTag": self.TAG,
            "checksum": actual,
            "fileSize": len(payload),
            "releaseStatus": "pending_review",
        }
        rows = [exact] if rows is None else [{**exact, **row} for row in rows]
        (directory / "pending.json").write_text(
            pending if pending is not None else json.dumps({"success": True, "data": {"releases": rows, "total": len(rows)}})
        )
        data = {"kind": kind, "version": self.VERSION, "releaseStatus": "pending_review"}
        data.update({"pluginId": self.PLUGIN_ID, "versionId": self.VERSION_ID} if kind == "plugin_version"
                    else {"submissionId": self.SUBMISSION_ID})
        (directory / "post.json").write_text(json.dumps({"success": True, "data": data}))
        for name_ in ("calls", "witness_calls", "gh_calls", "output", "summary"):
            (directory / name_).write_text("")
        declared = checksum or actual
        env = {
            "PATH": f"{directory}{os.pathsep}/usr/bin:/bin",
            "CALLS": str(directory / "calls"),
            "POST_BODY_FILE": str(directory / "post.json"),
            "POST_CODE": post_code,
            "GET_CODE": get_code,
            "PENDING_FILE": str(directory / "pending.json"),
            "WITNESS_CALLS": str(directory / "witness_calls"),
            "WITNESS_FILE": str(directory / "witness.json"),
            "WITNESS_CODE": witness_code,
            "GH_CALLS": str(directory / "gh_calls"),
            "GH_EXIT": gh_exit,
            "RELEASES_FILE": str(directory / "releases.json"),
            "GH_TOKEN": "fixture-github-token",
            "BEPLY_API_URL": "https://dev.fixture.invalid",
            "BEPLY_CI_TOKEN": token,
            "PLUGIN_NAME": name,
            "PLUGIN_VERSION": self.VERSION,
            "CHECKSUM": declared,
            "FILE_SIZE": str(file_size if file_size is not None else len(payload)),
            "RELEASE_TRACK": "main",
            "HAS_ATTESTATION": attestation,
            "SOURCE_PUBLISHED_AT": "2026-10-08T00:00:00Z",
            "SUBMIT_SOURCE_PROVENANCE": provenance,
            "SOURCE_PROVENANCE_ENVIRONMENT": "dev",
            "MANIFEST_ARTIFACT_ID": "7",
            "PUBLISHER_JOB_ID": "8",
            "GITHUB_REPOSITORY": self.REPOSITORY,
            "GITHUB_REF_NAME": self.TAG,
            "GITHUB_SHA": "e" * 40,
            "GITHUB_RUN_ID": "5",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(directory / "output"),
            "GITHUB_STEP_SUMMARY": str(directory / "summary"),
        }
        identity = self._step("catalog_identity")[1]["run"]
        self.assertNotIn("${{", identity, "catalog_identity must read its inputs from env")
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-c", identity],
            env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        if result.returncode == 0:
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-c", self._script(declared)],
                env=env, capture_output=True, text=True, check=False, timeout=60,
            )
        calls = (directory / "calls").read_text().splitlines()
        self.witness_calls = (directory / "witness_calls").read_text().splitlines()
        self.gh_calls = (directory / "gh_calls").read_text().splitlines()
        return result, calls, (directory / "output").read_text(), exact

    def test_exactly_one_matching_pending_row_is_the_only_green(self) -> None:
        for attestation, provenance in (("false", "false"), ("true", "true")):
            with self.subTest(attestation=attestation, provenance=provenance):
                result, calls, output, _ = self._run(attestation=attestation, provenance=provenance)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(len(calls), 2)
                self.assertIn("-X POST", calls[0])
                self.assertIn("https://dev.fixture.invalid/api/v1/plugins/release", calls[0])
                self.assertNotIn("-X POST", calls[1])
                self.assertIn("Authorization: Bearer fixture-token", calls[1])
                self.assertTrue(calls[1].endswith("https://dev.fixture.invalid/api/v1/plugins/pending-releases"))
                self.assertIn("candidate_kind=plugin_version\n", output)
                self.assertIn(f"version_id={self.VERSION_ID}\n", output)

    def test_unrelated_rows_and_identity_casing_do_not_change_the_witness(self) -> None:
        unrelated = {"versionId": "66666666-6666-4666-8666-666666666666", "version": "0.9", "sourceReleaseTag": "v0.9"}
        for rows in ([{}, unrelated], [{"sourceRepoFullName": self.REPOSITORY.upper()}]):
            with self.subTest(rows=rows):
                result, _, output, _ = self._run(rows)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("candidate_kind=plugin_version\n", output)

    def test_missing_duplicate_or_foreign_rows_fail_closed(self) -> None:
        foreign = {
            "sourceRepoFullName": "beply-es/OtherPlugin",
            "sourceReleaseTag": "v1.1",
            "pluginSlug": "otherplugin",
            "version": "1.1",
            "checksum": "sha256:" + "0" * 64,
            "fileSize": 1,
            "pluginId": "77777777-7777-4777-8777-777777777777",
            "versionId": "88888888-8888-4888-8888-888888888888",
        }
        cases = {"no row": [], "duplicate row": [{}, {}]}
        cases.update({f"foreign {field}": [{field: value}] for field, value in foreign.items()})
        cases["missing versionId"] = [{"versionId": None}]
        for label, rows in cases.items():
            with self.subTest(case=label):
                result, calls, output, _ = self._run(rows)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("expected exactly 1 pending row", result.stdout)
                self.assertEqual(len(calls), 2)
                self.assertNotIn("candidate_kind=", output)

    def test_submission_has_no_catalog_row_and_fails_closed(self) -> None:
        result, calls, output, _ = self._run(kind="plugin_submission")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("submission", result.stdout)
        self.assertEqual(len(calls), 1, "a submission must not be reported through any later read")
        self.assertEqual(output, "")

    def test_rejected_upload_or_unreadable_catalog_fails_closed(self) -> None:
        cases = {
            "upload rejected": ({"post_code": "500"}, 1),
            "catalog unreadable": ({"get_code": "503"}, 2),
            "catalog not json": ({"pending": "<html>maintenance</html>"}, 2),
            "catalog without releases": ({"pending": json.dumps({"success": True, "data": {}})}, 2),
        }
        for label, (kwargs, expected_calls) in cases.items():
            with self.subTest(case=label):
                result, calls, output, _ = self._run(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(calls), expected_calls)
                self.assertNotIn("candidate_kind=", output)

    def test_bytes_that_differ_from_the_measured_asset_are_never_posted(self) -> None:
        for label, kwargs in {
            "checksum": {"checksum": "sha256:" + "1" * 64},
            "size": {"file_size": 1},
        }.items():
            with self.subTest(drift=label):
                result, calls, output, _ = self._run(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])
                self.assertEqual(output, "")

    def test_readback_is_in_the_upload_step_and_blocking(self) -> None:
        publish, step = self._step()
        for policy in ("if", "continue-on-error"):
            with self.subTest(policy=policy):
                self.assertNotIn(policy, publish)
                self.assertNotIn(policy, step)
        body = step["run"]
        self.assertIn('"${BEPLY_API_URL}/api/v1/plugins/release"', body)
        self.assertIn('"${BEPLY_API_URL}/api/v1/plugins/pending-releases"', body)
        self.assertLess(body.index("/api/v1/plugins/release\""), body.index("/api/v1/plugins/pending-releases"))

    def test_new_plugin_is_refused_before_any_upload(self) -> None:
        current = {"tag_name": self.TAG, "draft": False}
        not_found = {"success": False, "error": "Exact persisted release witness not found", "code": "RELEASE_WITNESS_NOT_FOUND"}
        cases = {
            "first release": {"releases": [current]},
            "only non-version releases": {"releases": [current, {"tag_name": "main-" + "a" * 40, "draft": False},
                                                       {"tag_name": "docs-dev-20260916", "draft": False}]},
            "only a draft before": {"releases": [current, {"tag_name": "v0.9", "draft": True}]},
            "previous version unknown to DEV": {"witness_code": "404", "witness": not_found},
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                result, calls, output, _ = self._run(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(self.NEW_PLUGIN, result.stdout)
                self.assertEqual(result.stdout.count("::error::"), 1, result.stdout)
                self.assertEqual(calls, [], "a new plugin must not reach any upload")
                self.assertEqual(output, "")
                if "witness_code" not in kwargs:
                    self.assertEqual(self.witness_calls, [], "without a previous release there is nothing to read")

    def test_an_unreadable_catalog_is_red_and_never_read_as_a_new_plugin(self) -> None:
        cases = {
            "server error": {"witness_code": "500", "witness": {"success": False, "code": "INTERNAL_ERROR"}},
            "unavailable": {"witness_code": "503", "witness": "<html>maintenance</html>"},
            "unknown route": {"witness_code": "404", "witness": {"success": False, "code": "NOT_FOUND"}},
            "html 404": {"witness_code": "404", "witness": "<html>not found</html>"},
            "ambiguous owner": {"witness_code": "409", "witness": {"success": False, "code": "RELEASE_WITNESS_AMBIGUOUS"}},
            "unauthorized": {"witness_code": "401", "witness": {"success": False, "code": "UNAUTHORIZED"}},
            "foreign slug": {"witness_changes": {"pluginSlug": "otherplugin"}},
            "foreign version": {"witness_changes": {"version": "0.8"}},
            "no plugin id": {"witness_changes": {"pluginId": ""}},
            "unclaimed": {"witness_changes": {"claimed": False}},
            "not success": {"witness": {"success": False, "data": {}}},
            "github unreadable": {"gh_exit": "1"},
            "no catalog token": {"token": ""},
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                result, calls, output, _ = self._run(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("plugin nuevo", result.stdout)
                self.assertEqual(calls, [])
                self.assertEqual(output, "")
                if label == "no catalog token":
                    self.assertEqual((self.gh_calls, self.witness_calls), ([], []))

    def test_existing_plugin_is_proven_by_its_previous_release_in_dev(self) -> None:
        releases = [
            {"tag_name": self.TAG, "draft": False},
            {"tag_name": "main-" + "b" * 40, "draft": False},
            {"tag_name": "v0.95", "draft": True},
            {"tag_name": "v0.9", "draft": False},
            {"tag_name": "v0.8", "draft": False},
        ]
        result, calls, output, exact = self._run(releases=releases)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(self.gh_calls), 1)
        self.assertIn(f"repos/{self.REPOSITORY}/releases", self.gh_calls[0])
        self.assertEqual(len(self.witness_calls), 1)
        query = self.witness_calls[0]
        for fragment in ("Authorization: Bearer fixture-token", f"sourceRepoFullName={self.REPOSITORY}",
                         f"pluginSlug={exact['pluginSlug']}", "version=0.9",
                         "https://dev.fixture.invalid/api/v1/plugins/release-witness"):
            self.assertIn(fragment, query)
        self.assertNotIn("-X POST", query)
        self.assertEqual(len(calls), 2)
        self.assertIn("candidate_kind=plugin_version\n", output)

    def test_catalog_identity_runs_unconditionally_before_any_effect(self) -> None:
        publish, step = self._step("catalog_identity")
        names = [item.get("name") for item in publish["steps"]]
        for later in ("attestation", "upload_dev"):
            with self.subTest(before=later):
                after = next(item for item in publish["steps"] if item.get("id") == later)
                self.assertLess(names.index(step["name"]), names.index(after["name"]))
        for policy in ("if", "continue-on-error"):
            self.assertNotIn(policy, step)
        env = step["env"]
        self.assertEqual(env["BEPLY_API_URL"], "${{ inputs.dev_api_url }}")
        self.assertEqual(env["BEPLY_CI_TOKEN"], "${{ secrets.BEPLY_DEV_CI_TOKEN }}")
        self.assertEqual(env["PLUGIN_NAME"], "${{ needs.source_provenance.outputs.plugin_name }}")
        self.assertEqual(env["GH_TOKEN"], "${{ github.token }}")
        self.assertIn(self.NEW_PLUGIN, step["run"])


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


class RuntimePhpContractTests(unittest.TestCase):
    """El runtime de tenant es `php:8.2-fpm-alpine` (beply-k3s
    docker-build/facturascripts-runtime). El backend rechaza una release cuyo
    `min_php` supera ese runtime (PLUGIN_MIN_PHP_EXCEEDS_RUNTIME), asi que el
    plugin no puede exigir mas, y la CI tiene que probar en esa version. PHP 8.4
    se vigila como compatibilidad hacia delante, sin bloquear.
    """

    ROOT = Path(__file__).resolve().parents[2]
    RUNTIME_PHP = (8, 2)

    def _jobs(self):
        return yaml.safe_load((self.ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8"))["jobs"]

    def test_manifest_never_requires_more_php_than_the_runtime(self) -> None:
        ini = (self.ROOT / "facturascripts.ini").read_text(encoding="utf-8")
        match = re.search(r"(?m)^min_php\s*=\s*['\"]?(\d+)\.(\d+)['\"]?\s*$", ini)
        self.assertIsNotNone(match, "facturascripts.ini must declare min_php as X.Y")
        self.assertLessEqual((int(match.group(1)), int(match.group(2))), self.RUNTIME_PHP)

    def test_ci_tests_on_the_runtime_php(self) -> None:
        jobs = self._jobs()
        runtime = "%d.%d" % self.RUNTIME_PHP
        for name in ("unit", "runtime"):
            with self.subTest(job=name):
                self.assertEqual(jobs[name]["strategy"]["matrix"]["php-version"], [runtime])
        for name in ("lint", "e2e"):
            with self.subTest(job=name):
                setup = next(step for step in jobs[name]["steps"] if str(step.get("uses", "")).startswith("shivammathur/setup-php@"))
                self.assertEqual(str(setup["with"]["php-version"]), runtime)
        workflow = (self.ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertFalse("platform.php 8.4" in workflow, "composer must resolve for the runtime PHP")
        self.assertEqual(workflow.count("composer config platform.php"), workflow.count(f"composer config platform.php {runtime}.0"))
        unit = next(step for step in jobs["unit"]["steps"] if step.get("name") == "Run PHPUnit unit suite")
        self.assertIn(f"matrix.php-version == '{runtime}'", unit["if"], "the unit suite must run on the runtime PHP")

    def test_php84_scan_is_forward_compatibility_and_never_blocks(self) -> None:
        job = self._jobs()["php84_compat"]
        self.assertIs(job.get("continue-on-error"), True)
        setup = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("shivammathur/setup-php@"))
        self.assertEqual(str(setup["with"]["php-version"]), "8.4")

