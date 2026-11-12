import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "facturascripts.ini",
    ".github/workflows/release.yml",
    ".github/workflows/promote-prod.yml",
    "scripts/ci/test_immutable_plugin_contract.py",
    "scripts/ci/build_plugin_zip.py",
    "scripts/ci/immutable_plugin_contract.py",
)
PIN = "a" * 40
OTHER_PIN = "b" * 40
PREFIX = "beply-es/BeplyPluginTemplate/.github/workflows/"


class TemplatePinContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def replace(self, name, old, new):
        path = self.root / name
        content = path.read_text(encoding="utf-8")
        self.assertEqual(content.count(old), 1, name)
        path.write_text(content.replace(old, new), encoding="utf-8")

    def as_plugin(self):
        self.replace("facturascripts.ini", "name = BeplyPluginTemplate", "name = BeplyDemo")
        for name, workflow in (
            ("release.yml", "reusable-immutable-plugin-candidate.yml"),
            ("promote-prod.yml", "reusable-promote-immutable-plugin-candidate.yml"),
        ):
            path = ".github/workflows/" + name
            self.replace(path, "uses: ./.github/workflows/" + workflow, "uses: " + PREFIX + workflow + "@" + PIN)
            self.replace(path, "contract_sha: ${{ github.sha }}", "contract_sha: " + PIN)

    def check_contract(self, expected_success):
        result = subprocess.run(
            ["python3", "-m", "unittest", "scripts.ci.test_immutable_plugin_contract.SourceProvenanceCarrierTests.test_release_and_promotion_call_one_template_contract"],
            cwd=self.root, capture_output=True, text=True, check=False,
            env={**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")},
        )
        if expected_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("AssertionError", result.stderr)

    def test_template(self):
        self.check_contract(True)

    def test_plugin_matching_pins(self):
        self.as_plugin()
        self.check_contract(True)

    def test_plugin_promotion_pin_differs(self):
        self.as_plugin()
        self.replace(".github/workflows/promote-prod.yml", "candidate.yml@" + PIN, "candidate.yml@" + OTHER_PIN)
        self.check_contract(False)
        self.replace(".github/workflows/promote-prod.yml", "contract_sha: " + PIN, "contract_sha: " + OTHER_PIN)
        self.check_contract(False)

    def test_plugin_promotion_contract_sha_expression(self):
        self.as_plugin()
        self.replace(".github/workflows/promote-prod.yml", "contract_sha: " + PIN, "contract_sha: ${{ github.sha }}")
        self.check_contract(False)

    def test_plugin_release_contract_sha_differs(self):
        self.as_plugin()
        self.replace(".github/workflows/release.yml", "contract_sha: " + PIN, "contract_sha: " + OTHER_PIN)
        self.check_contract(False)

    def test_plugin_local_calls(self):
        self.replace("facturascripts.ini", "name = BeplyPluginTemplate", "name = BeplyDemo")
        self.check_contract(False)

    def test_template_pinned_release(self):
        workflow = "reusable-immutable-plugin-candidate.yml"
        self.replace(".github/workflows/release.yml", "uses: ./.github/workflows/" + workflow, "uses: " + PREFIX + workflow + "@" + PIN)
        self.check_contract(False)

    def append_job(self, workflow, key, uses, contract_sha=None):
        path = self.root / ".github/workflows" / workflow
        with path.open("a", encoding="utf-8") as output:
            output.write(f"\n  {key}:\n    uses: {uses}\n")
            if contract_sha is not None:
                output.write(f"    with:\n      contract_sha: {contract_sha}\n")

    def test_extra_candidate_other_pin(self):
        self.as_plugin()
        self.append_job("release.yml", "extra_candidate", PREFIX + "reusable-immutable-plugin-candidate.yml@" + OTHER_PIN, OTHER_PIN)
        self.check_contract(False)

    def test_extra_promote_other_pin_and_expression(self):
        self.as_plugin()
        uses = PREFIX + "reusable-promote-immutable-plugin-candidate.yml@"
        self.append_job("promote-prod.yml", "extra_promote", uses + OTHER_PIN, "${{ github.sha }}")
        self.check_contract(False)
        self.replace(".github/workflows/promote-prod.yml", uses + OTHER_PIN, uses + PIN)
        self.check_contract(False)

    def test_release_rejects_branch_and_tag(self):
        for ref in ("main", "v1.5"):
            with self.subTest(ref=ref):
                self.as_plugin()
                path = ".github/workflows/release.yml"
                self.replace(path, "candidate.yml@" + PIN, "candidate.yml@" + ref)
                self.check_contract(False)
                self.replace(path, "contract_sha: " + PIN, "contract_sha: " + ref)
                self.check_contract(False)
                promote = ".github/workflows/promote-prod.yml"
                self.replace(promote, "candidate.yml@" + PIN, "candidate.yml@" + ref)
                self.replace(promote, "contract_sha: " + PIN, "contract_sha: " + ref)
                self.check_contract(False)
                shutil.copyfile(ROOT / "facturascripts.ini", self.root / "facturascripts.ini")
                shutil.copyfile(ROOT / path, self.root / path)
                shutil.copyfile(ROOT / ".github/workflows/promote-prod.yml", self.root / ".github/workflows/promote-prod.yml")

    def test_extra_candidate_matching_pin(self):
        self.as_plugin()
        self.append_job("release.yml", "extra_candidate", PREFIX + "reusable-immutable-plugin-candidate.yml@" + PIN, PIN)
        self.check_contract(True)

    def test_extra_unrelated_local_workflow(self):
        self.as_plugin()
        self.append_job("release.yml", "extra_local", "./.github/workflows/otro-workflow-propio.yml")
        self.check_contract(True)


if __name__ == "__main__":
    unittest.main()
