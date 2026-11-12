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


if __name__ == "__main__":
    unittest.main()
