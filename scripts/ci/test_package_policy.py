import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.ci.build_plugin_zip import BuildError, build_plugin_zip


class PackagePolicyTests(unittest.TestCase):
    """Opt-in por repositorio: `.beply/package-policy.json` puede conservar subdirectorios de scripts/
    que el plugin necesita en producción (p. ej. scripts/runtime). Sin el fichero, nada cambia."""

    def _plugin(self, tmp: str) -> Path:
        root = Path(tmp) / "plugin"
        (root / "scripts" / "runtime").mkdir(parents=True)
        (root / "scripts" / "ci").mkdir(parents=True)
        (root / "facturascripts.ini").write_text("name = BeplyDemo\nversion = 1.2\n", encoding="utf-8")
        (root / "Init.php").write_text("<?php\n", encoding="utf-8")
        (root / "scripts" / "runtime" / "worker.php").write_text("<?php // runtime\n", encoding="utf-8")
        (root / "scripts" / "ci" / "build.py").write_text("dev tooling", encoding="utf-8")
        (root / "scripts" / "top.sh").write_text("dev tooling", encoding="utf-8")
        return root

    def _names(self, root: Path, tmp: str) -> list[str]:
        output = Path(tmp) / "candidate.zip"
        if output.exists():
            output.unlink()
        build_plugin_zip(root, output, "BeplyDemo", "1.2")
        with ZipFile(output) as archive:
            return archive.namelist()

    def test_without_policy_all_scripts_stay_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._plugin(tmp)
            self.assertEqual(self._names(root, tmp), ["BeplyDemo/Init.php", "BeplyDemo/facturascripts.ini"])

    def test_agent_instruction_files_never_ship(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._plugin(tmp)
            (root / "AGENTS.md").write_text("agent guide", encoding="utf-8")
            (root / "CLAUDE.md").write_text("agent guide", encoding="utf-8")
            (root / "Controller").mkdir()
            (root / "Controller" / "AGENTS.md").write_text("nested agent guide", encoding="utf-8")
            (root / "Controller" / "Demo.php").write_text("<?php\n", encoding="utf-8")
            for hidden in (".claude", ".agents", ".codex"):
                (root / hidden).mkdir()
                (root / hidden / "settings.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                self._names(root, tmp),
                ["BeplyDemo/Controller/Demo.php", "BeplyDemo/Init.php", "BeplyDemo/facturascripts.ini"],
            )

    def test_policy_keeps_only_the_declared_scripts_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._plugin(tmp)
            (root / ".beply").mkdir()
            (root / ".beply" / "package-policy.json").write_text(
                json.dumps({"schema": 1, "includeScripts": ["runtime"]}), encoding="utf-8")
            names = self._names(root, tmp)
            self.assertIn("BeplyDemo/scripts/runtime/worker.php", names)
            self.assertNotIn("BeplyDemo/scripts/ci/build.py", names)
            self.assertNotIn("BeplyDemo/scripts/top.sh", names)
            self.assertIn("BeplyDemo/.beply/package-policy.json", names)

    def test_policy_still_drops_env_files_inside_included_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._plugin(tmp)
            (root / "scripts" / "runtime" / ".env").write_text("SECRET=x", encoding="utf-8")
            (root / "scripts" / "runtime" / ".env.local").write_text("SECRET=x", encoding="utf-8")
            (root / ".beply").mkdir()
            (root / ".beply" / "package-policy.json").write_text(
                json.dumps({"schema": 1, "includeScripts": ["runtime"]}), encoding="utf-8")
            names = self._names(root, tmp)
            self.assertIn("BeplyDemo/scripts/runtime/worker.php", names)
            self.assertFalse(any(name.endswith((".env", ".env.local")) for name in names), names)

    def test_policy_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._plugin(tmp)
            (root / ".beply").mkdir()
            (root / ".beply" / "package-policy.json").write_text(
                json.dumps({"schema": 1, "includeScripts": ["runtime"]}), encoding="utf-8")
            first = build_plugin_zip(root, Path(tmp) / "a.zip", "BeplyDemo", "1.2")
            second = build_plugin_zip(root, Path(tmp) / "b.zip", "BeplyDemo", "1.2")
            self.assertEqual(first["checksum"], second["checksum"])

    def test_rejects_invalid_policies(self) -> None:
        bad = [
            "no json",
            json.dumps([]),
            json.dumps({"schema": 2, "includeScripts": ["runtime"]}),
            json.dumps({"schema": 1, "includeScripts": "runtime"}),
            json.dumps({"schema": 1, "includeScripts": ["../docs"]}),
            json.dumps({"schema": 1, "includeScripts": ["ci/x"]}),
            json.dumps({"schema": 1, "includeScripts": ["runtime"], "excludeRoots": ["Lib"]}),
        ]
        for text in bad:
            with self.subTest(policy=text), tempfile.TemporaryDirectory() as tmp:
                root = self._plugin(tmp)
                (root / ".beply").mkdir()
                (root / ".beply" / "package-policy.json").write_text(text, encoding="utf-8")
                with self.assertRaises(BuildError):
                    build_plugin_zip(root, Path(tmp) / "candidate.zip", "BeplyDemo", "1.2")

    def test_symlinked_policy_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._plugin(tmp)
            (root / ".beply").mkdir()
            target = Path(tmp) / "policy.json"
            target.write_text(json.dumps({"schema": 1, "includeScripts": ["runtime"]}), encoding="utf-8")
            (root / ".beply" / "package-policy.json").symlink_to(target)
            with self.assertRaises(BuildError):
                build_plugin_zip(root, Path(tmp) / "candidate.zip", "BeplyDemo", "1.2")
