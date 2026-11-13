"""Dependencias de CI declaradas en .beply/ci-dependencies.json (TAREA-647.5).

tests.yml clona hasta cuatro plugins de beply-es en Unit, Runtime y E2E con la clave de lectura
que nombra la lista. Sin lista, cada hueco se salta y el runtime recibe solo el plugin, así que
la CI sale igual que antes. Este test fija esa forma: los huecos, su condición, la clave sin
persistir y que ningún otro paso lea un secreto por nombre dinámico. setup-runtime.php cambia de
secuencia solo con dependencias; sin ellas, la secuencia de siempre.
"""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/tests.yml"
SETUP = ROOT / ".github/ci/setup-runtime.php"
SLOTS = (1, 2, 3, 4)
DEP_JOBS = ("unit", "runtime", "e2e")
NO_DEP_JOBS = ("quality_contract", "php84_compat", "lint")
OUT = "needs.quality_contract.outputs."
CHECKOUT = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"

# La secuencia que setup-runtime.php ejecutaba antes de este cambio, y la que BeplyServicios ya
# probó en verde con BeplyProyectos y StockAvanzado.
WITHOUT_DEPENDENCIES = [
    "seedRequestedPlugins", "persistRequestedPlugins", "deployRequestedPlugins", "ensureCoreTables",
    "seedCoreCatalogData", "seedDefaultSettings", "initializeRequestedPlugins", "seedDefaultSettings",
]
WITH_DEPENDENCIES = [
    "ensureCoreTables", "deployCoreRuntime", "seedCoreCompany", "seedCoreCatalogData", "seedDefaultSettings",
    "seedRequestedPlugins", "persistRequestedPlugins", "deployRequestedPlugins", "ensurePluginBaseTables",
    "initializeRequestedPlugins", "seedDefaultSettings", "bootstrapFileSystem",
]


def load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def step_index(steps, name):
    names = [step.get("name") for step in steps]
    return names.index(name)


class CiDependenciesWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load()
        self.jobs = self.workflow["jobs"]

    def test_quality_contract_reads_the_list_and_exposes_every_slot(self):
        job = self.jobs["quality_contract"]
        steps = [s for s in job["steps"] if "read-ci-dependencies.mjs" in str(s.get("run", ""))]
        self.assertEqual(1, len(steps))
        self.assertEqual("ci-deps", steps[0].get("id"))
        self.assertIn('>> "$GITHUB_OUTPUT"', steps[0]["run"])
        expected = {
            key: "${{ steps.ci-deps.outputs.%s }}" % key
            for key in ["has_dependencies", "plugin_folders", "dependency_folders"]
            + [f"dep{n}_{field}" for n in SLOTS for field in ("repository", "ref", "folder", "ssh_key_secret")]
        }
        for key, value in expected.items():
            self.assertEqual(value, job["outputs"].get(key), key)

    def test_each_heavy_job_has_four_conditional_read_only_checkouts(self):
        for job_name in DEP_JOBS:
            steps = self.jobs[job_name]["steps"]
            plugin = step_index(steps, "Checkout Plugin")
            for n in SLOTS:
                with self.subTest(job=job_name, slot=n):
                    index = step_index(steps, f"Checkout CI dependency {n}")
                    self.assertEqual(plugin + 1 + n, index, "los huecos van seguidos tras la comprobación de claves")
                    step = steps[index]
                    self.assertEqual(f"{OUT}dep{n}_repository != ''", step.get("if"))
                    self.assertTrue(step["uses"].startswith(CHECKOUT), step["uses"])
                    self.assertEqual({
                        "repository": "${{ %sdep%d_repository }}" % (OUT, n),
                        "ref": "${{ %sdep%d_ref }}" % (OUT, n),
                        "ssh-key": "${{ secrets[%sdep%d_ssh_key_secret] }}" % (OUT, n),
                        "path": "facturascripts/Plugins/${{ %sdep%d_folder }}" % (OUT, n),
                        "persist-credentials": False,
                    }, step["with"])
                    self.assertNotIn("env", step)

    def test_a_missing_named_secret_fails_with_its_name_before_any_checkout(self):
        for job_name in DEP_JOBS:
            with self.subTest(job=job_name):
                steps = self.jobs[job_name]["steps"]
                index = step_index(steps, "Check CI dependency keys")
                self.assertEqual(step_index(steps, "Checkout Plugin") + 1, index)
                step = steps[index]
                self.assertEqual(f"{OUT}has_dependencies == 'true'", step.get("if"))
                expected = {}
                for n in SLOTS:
                    expected[f"DEP{n}_SECRET"] = "${{ %sdep%d_ssh_key_secret }}" % (OUT, n)
                    expected[f"DEP{n}_KEY_SET"] = "${{ secrets[%sdep%d_ssh_key_secret] != '' }}" % (OUT, n)
                self.assertEqual(expected, step["env"])
                run = step["run"]
                self.assertIn('"${!set_var}" != "true"', run)
                self.assertIn("::error::Falta el secreto ${!name_var}", run)
                self.assertIn('exit "${missing}"', run)
                self.assertNotIn("set -x", run)

    def test_no_other_step_reads_a_secret_by_dynamic_name(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        checkout = {"${{ secrets[%sdep%d_ssh_key_secret] }}" % (OUT, n) for n in SLOTS}
        presence = {"${{ secrets[%sdep%d_ssh_key_secret] != '' }}" % (OUT, n) for n in SLOTS}
        found = re.findall(r"\$\{\{[^}]*secrets\[[^}]*\}\}", text)
        self.assertEqual(2 * len(DEP_JOBS) * len(SLOTS), len(found))
        self.assertEqual(checkout | presence, set(found))
        self.assertEqual(len(found), text.count("secrets["), "ningún secrets[ fuera de esas expresiones")

    def test_lists_never_expose_more_than_names(self):
        reader = (ROOT / "scripts/ci/read-ci-dependencies.mjs").read_text(encoding="utf-8")
        self.assertNotIn("process.env)", reader)
        self.assertNotIn("set -x", WORKFLOW.read_text(encoding="utf-8"))

    def test_sync_policy_never_overwrites_the_plugin_list(self):
        import json
        policy = json.loads((ROOT / ".beply/template-sync.json").read_text(encoding="utf-8"))
        self.assertIn(".beply/ci-dependencies.json", policy["neverOverwrite"])
        self.assertNotIn(".beply/ci-dependencies.json", policy["overwrite"] + policy["createIfMissing"])
        for script in ("scripts/ci/read-ci-dependencies.mjs", "scripts/ci/test_ci_dependencies.mjs",
                       "scripts/ci/test_ci_dependencies_workflow.py"):
            self.assertIn(script, policy["overwrite"])
        self.assertFalse((ROOT / ".beply/ci-dependencies.json").exists(), "la plantilla no trae lista propia")

    def test_heavy_jobs_already_needed_quality_contract(self):
        # Unit, Runtime y E2E ya dependían de Quality Contract (por fs_refs): leer aquí la lista
        # no añade ningún needs ni serializa nada nuevo.
        for job_name in DEP_JOBS:
            self.assertEqual(["quality_contract", "lint"], self.jobs[job_name]["needs"], job_name)

    def test_light_jobs_do_not_clone_dependencies(self):
        for job_name in NO_DEP_JOBS:
            names = [step.get("name", "") for step in self.jobs[job_name]["steps"]]
            self.assertFalse([n for n in names if n.startswith("Checkout CI dependency")], job_name)

    def test_runtime_receives_the_plugin_plus_declared_dependencies(self):
        for job_name in ("runtime", "e2e"):
            steps = self.jobs[job_name]["steps"]
            step = steps[step_index(steps, "Prepare plugin runtime")]
            self.assertEqual({
                "CI_PLUGIN_FOLDERS": "${{ %splugin_folders }}" % OUT,
                "CI_PLUGIN_DEPENDENCIES": "${{ %sdependency_folders }}" % OUT,
            }, step["env"], job_name)
            last_checkout = step_index(steps, f"Checkout CI dependency {SLOTS[-1]}")
            self.assertLess(last_checkout, steps.index(step))


def call_sequence(block):
    return re.findall(r"^\s*([A-Za-z]+)\(\);\s*$", block, re.MULTILINE)


class SetupRuntimeSequenceTests(unittest.TestCase):
    def setUp(self):
        text = SETUP.read_text(encoding="utf-8")
        match = re.search(
            r"^if \(requestedDependencyFolders\(\) === \[\]\) \{\n(?P<without>.*?)^\} else \{\n(?P<with>.*?)^\}\n",
            text, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, "setup-runtime.php debe elegir la secuencia por requestedDependencyFolders()")
        self.match = match
        self.text = text

    def test_without_dependencies_the_sequence_is_unchanged(self):
        self.assertEqual(WITHOUT_DEPENDENCIES, call_sequence(self.match.group("without")))

    def test_with_dependencies_the_sequence_is_the_one_proven_in_servicios(self):
        self.assertEqual(WITH_DEPENDENCIES, call_sequence(self.match.group("with")))

    def test_dependencies_must_be_requested_plugins(self):
        body = re.search(r"function requestedDependencyFolders\(\): array\n\{\n(.*?)^\}", self.text, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("CI_PLUGIN_DEPENDENCIES", body.group(1))
        self.assertIn("requestedPluginFolders()", body.group(1))
        self.assertIn("RuntimeException", body.group(1))


if __name__ == "__main__":
    unittest.main()
