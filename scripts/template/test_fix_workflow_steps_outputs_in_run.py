#!/usr/bin/env python3
"""TDD tests for scripts/template/fix_workflow_steps_outputs_in_run.py.

Covers:
1. RED -> GREEN on real A2 and C workflow fixtures (all parse cleanly with PyYAML).
2. Idempotency: 2nd pass over transformed tree yields diff = 0 bytes.
3. Normalized diff SHA-256: two repos from the same family yield the exact same hash.
4. Security: malicious ini name `x$(id)` is never interpolated in run: after transformation.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import fix_workflow_steps_outputs_in_run as gen  # noqa: E402

FIXTURES_DIR = SCRIPT_DIR / 'fixtures' / 'steps_outputs_in_run'
ALL_FIXTURE_REPOS = (
    'BeplyA3',
    'BeplyDelsol',
    'BeplyCashBox',
    'Tickets',
    'BeplyCartaPortes',
    'BeplyComisiones',
)


def _copy_fixture(repo_name: str, dest: Path) -> Path:
    src = FIXTURES_DIR / repo_name
    target = dest / repo_name
    shutil.copytree(src, target)
    return target


def _run_contract_test(repo_dir: Path) -> subprocess.CompletedProcess[str]:
    test_file = repo_dir / gen.CONTRACT_TEST_REL_PATH
    if not test_file.is_file():
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(gen.CONTRACT_TEST_SOURCE, encoding='utf-8')
    return subprocess.run(
        [sys.executable, '-B', '-m', 'unittest', str(test_file)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


class FixWorkflowStepsOutputsInRunTest(unittest.TestCase):
    def test_red_to_green_on_all_real_a2_and_c_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for repo_name in ALL_FIXTURE_REPOS:
                with self.subTest(repo=repo_name):
                    repo_dir = _copy_fixture(repo_name, tmp_path)

                    # RED before generator
                    red = _run_contract_test(repo_dir)
                    self.assertNotEqual(
                        0,
                        red.returncode,
                        f'Expected RED before generator on {repo_name}, got exit 0',
                    )

                    # Apply generator
                    res = gen.process_repository(repo_dir, apply=True, repo_name=repo_name)
                    self.assertTrue(res.changed_files, f'Expected changes for {repo_name}')
                    self.assertGreater(res.diff_bytes, 0)
                    self.assertEqual(64, len(res.normalized_diff_sha256))

                    # Every resulting workflow parses cleanly with PyYAML
                    for wf in sorted((repo_dir / '.github' / 'workflows').glob('*.yml')):
                        parsed = yaml.safe_load(wf.read_text(encoding='utf-8'))
                        self.assertIsInstance(parsed, dict)

                    # GREEN after generator
                    green = _run_contract_test(repo_dir)
                    self.assertEqual(
                        0,
                        green.returncode,
                        f'Expected GREEN after generator on {repo_name}:\n{green.stdout}\n{green.stderr}',
                    )

    def test_idempotency_second_pass_produces_zero_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for repo_name in ALL_FIXTURE_REPOS:
                with self.subTest(repo=repo_name):
                    repo_dir = _copy_fixture(repo_name, tmp_path)
                    first = gen.process_repository(repo_dir, apply=True, repo_name=repo_name)
                    self.assertGreater(first.diff_bytes, 0)

                    snapshot_before = {
                        p.relative_to(repo_dir).as_posix(): p.read_bytes()
                        for p in sorted(repo_dir.rglob('*'))
                        if p.is_file()
                    }

                    second = gen.process_repository(repo_dir, apply=True, repo_name=repo_name)
                    self.assertEqual([], second.changed_files)
                    self.assertEqual(0, second.diff_bytes)

                    snapshot_after = {
                        p.relative_to(repo_dir).as_posix(): p.read_bytes()
                        for p in sorted(repo_dir.rglob('*'))
                        if p.is_file()
                    }
                    self.assertEqual(snapshot_before, snapshot_after)

    def test_normalized_diff_sha256_matches_within_same_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Same A2 ini.name family: BeplyA3 release.yml vs BeplyDelsol release.yml
            a3 = tmp_path / 'BeplyA3'
            delsol = tmp_path / 'BeplyDelsol'
            (a3 / '.github' / 'workflows').mkdir(parents=True)
            (delsol / '.github' / 'workflows').mkdir(parents=True)
            shutil.copy2(
                FIXTURES_DIR / 'BeplyA3' / '.github' / 'workflows' / 'release.yml',
                a3 / '.github' / 'workflows' / 'release.yml',
            )
            shutil.copy2(
                FIXTURES_DIR / 'BeplyDelsol' / '.github' / 'workflows' / 'release.yml',
                delsol / '.github' / 'workflows' / 'release.yml',
            )

            r_a3 = gen.process_repository(a3, apply=False, repo_name='BeplyA3')
            r_delsol = gen.process_repository(delsol, apply=False, repo_name='BeplyDelsol')

            self.assertGreater(r_a3.diff_bytes, 0)
            self.assertEqual(
                r_a3.normalized_diff_sha256,
                r_delsol.normalized_diff_sha256,
                f'Expected identical normalized diff hash for same A2 family:\n'
                f'--- BeplyA3 ---\n{r_a3.normalized_diff}\n'
                f'--- BeplyDelsol ---\n{r_delsol.normalized_diff}',
            )

    def test_security_malicious_ini_name_is_never_interpolated_in_run(self) -> None:
        workflow_with_ini_name = """name: Release
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Parse ini
        id: ini
        run: echo "name=x$(id)" >> "$GITHUB_OUTPUT"
      - name: Build zip
        run: python3 scripts/ci/build-plugin-zip.py --output "/tmp/${{ steps.ini.outputs.name }}-v${{ steps.ini.outputs.version }}.zip"
"""
        transformed = gen.transform_workflow_text(workflow_with_ini_name)
        data = yaml.safe_load(transformed)
        build_step = data['jobs']['build']['steps'][1]

        # Must pass through env:
        self.assertEqual('${{ steps.ini.outputs.name }}', build_step['env']['PLUGIN_NAME'])
        self.assertEqual('${{ steps.ini.outputs.version }}', build_step['env']['PLUGIN_VERSION'])
        # Must NOT interpolate steps.ini.outputs.* in run:
        self.assertNotIn('steps.ini.outputs.name', build_step['run'])
        self.assertNotIn('steps.ini.outputs.version', build_step['run'])
        self.assertIn('"/tmp/${PLUGIN_NAME}-v${PLUGIN_VERSION}.zip"', build_step['run'])

        # Execute the transformed shell command with malicious PLUGIN_NAME='x$(id)'
        # and verify $(id) is treated strictly as literal data, NEVER executed.
        probe = subprocess.run(
            ['bash', '-euo', 'pipefail', '-c', 'printf "%s" "/tmp/${PLUGIN_NAME}-v${PLUGIN_VERSION}.zip"'],
            env={'PLUGIN_NAME': 'x$(id)', 'PLUGIN_VERSION': '1.0'},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual('/tmp/x$(id)-v1.0.zip', probe.stdout)

    def test_dry_run_does_not_modify_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = _copy_fixture('BeplyCashBox', Path(tmp))
            before = (repo_dir / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')

            res = gen.process_repository(repo_dir, apply=False, repo_name='BeplyCashBox')
            self.assertFalse(res.applied)
            self.assertGreater(res.diff_bytes, 0)
            after = (repo_dir / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')
            self.assertEqual(before, after)
            self.assertFalse((repo_dir / gen.CONTRACT_TEST_REL_PATH).exists())


if __name__ == '__main__':
    unittest.main()
