#!/usr/bin/env python3
"""TDD tests for scripts/template/fix_workflow_steps_outputs_in_run.py.

Covers:
1. RED -> GREEN on real A2 and C workflow fixtures (all parse cleanly with PyYAML).
2. Idempotency: 2nd pass over transformed tree yields diff = 0 bytes.
3. Normalized diff SHA-256: two repos from the same family yield the exact same hash.
4. Security: malicious ini name `x$(id)` is never interpolated in run: after transformation.
5. C1: preserves original quoting context (unquoted -> ${VAR} keeping word-splitting for *targets;
   double-quoted -> ${VAR} inside existing double quotes).
6. C2: single-quoted contexts ('prefix-${{ ... }}-suffix') close & reopen single quotes as
   'prefix-'"${VAR}"'-suffix' so bash expands the value without executing $(id).
7. C3: fail-closed on unsupported compound expressions and with.script (skips & warns,
   eligible_for_batch=False); injected contract test also rejects with.script.
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
                    self.assertTrue(res.eligible_for_batch)
                    self.assertEqual([], res.warnings)
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

    def test_c1_preserves_unquoted_word_splitting_and_blocks_injection(self) -> None:
        workflow = """name: Unit
on: push
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - name: Run targets
        run: |
          count=0
          for f in ${{ steps.unit-targets.outputs.targets }}; do count=$((count + 1)); done
          printf "%s:%s" "$count" "${{ steps.ini.outputs.name }}"
"""
        transformed = gen.transform_workflow_text(workflow)
        data = yaml.safe_load(transformed)
        step = data['jobs']['unit']['steps'][0]

        self.assertEqual('${{ steps.unit-targets.outputs.targets }}', step['env']['PHPUNIT_TARGETS'])
        self.assertEqual('${{ steps.ini.outputs.name }}', step['env']['PLUGIN_NAME'])
        self.assertIn('for f in ${PHPUNIT_TARGETS};', step['run'])
        self.assertNotIn('"${PHPUNIT_TARGETS}"', step['run'])
        self.assertIn('"${PLUGIN_NAME}"', step['run'])

        probe = subprocess.run(
            ['bash', '-euo', 'pipefail', '-c', step['run']],
            env={'PHPUNIT_TARGETS': 'a.php b.php', 'PLUGIN_NAME': 'x$(id)'},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual('2:x$(id)', probe.stdout)

        # Exact rev-be1996 C1 proof: set -- ${PHPUNIT_TARGETS}; echo $# -> 2
        wf_set = """name: Unit
on: push
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - name: Count args
        run: set -- ${{ steps.unit-targets.outputs.targets }}; echo $#
"""
        t_set = yaml.safe_load(gen.transform_workflow_text(wf_set))['jobs']['unit']['steps'][0]['run']
        probe_set = subprocess.run(
            ['bash', '-euo', 'pipefail', '-c', t_set],
            env={'PHPUNIT_TARGETS': 'a.php b.php'},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual('2', probe_set.stdout.strip())

    def test_c2_single_quoted_interpolation_closes_and_reopens_quotes_safely(self) -> None:
        workflow = """name: Deploy
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Print slug
        run: printf "%s" 'prefix-${{ steps.slug.outputs.slug }}-suffix'
"""
        transformed = gen.transform_workflow_text(workflow)
        data = yaml.safe_load(transformed)
        step = data['jobs']['deploy']['steps'][0]

        self.assertEqual('${{ steps.slug.outputs.slug }}', step['env']['STEP_SLUG_SLUG'])
        self.assertIn('\'prefix-\'"${STEP_SLUG_SLUG}"\'-suffix\'', step['run'])

        for slug_val, expected in (
            ('2.0-arm64', 'prefix-2.0-arm64-suffix'),
            ('x$(id)', 'prefix-x$(id)-suffix'),
        ):
            probe = subprocess.run(
                ['bash', '-euo', 'pipefail', '-c', step['run']],
                env={'STEP_SLUG_SLUG': slug_val},
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(expected, probe.stdout)

    def test_c2_single_quotes_inside_double_quoted_command_substitution(self) -> None:
        workflow = """name: Deploy
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Compute slug
        run: |
          slug="$(printf '%s' '${{ steps.x.outputs.x }}-arm64')"
          echo "$slug"
"""
        transformed = gen.transform_workflow_text(workflow)
        data = yaml.safe_load(transformed)
        step = data['jobs']['deploy']['steps'][0]

        self.assertEqual('${{ steps.x.outputs.x }}', step['env']['STEP_X_X'])
        self.assertIn('\'\'"${STEP_X_X}"\'-arm64\'', step['run'])

        for val, expected in (
            ('2.0', '2.0-arm64'),
            ('$(id)', '$(id)-arm64'),
        ):
            probe = subprocess.run(
                ['bash', '-euo', 'pipefail', '-c', step['run']],
                env={'STEP_X_X': val},
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(expected, probe.stdout.strip())

    def test_c4_post_transform_sweep_catches_multiline_double_quoted_yaml_and_needs_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / 'MultilineYamlRepo'
            wf_dir = repo_dir / '.github' / 'workflows'
            wf_dir.mkdir(parents=True)
            wf_path = wf_dir / 'canary.yml'
            original = (
                'name: Canary\n'
                'on: push\n'
                'jobs:\n'
                '  canary:\n'
                '    runs-on: ubuntu-latest\n'
                '    steps:\n'
                '      - name: Split scalar\n'
                '        run: "echo ${{ steps.foo.outputs.\n'
                '          bar }}"\n'
                '      - name: Needs output\n'
                '        run: echo "${{ needs.build.outputs.tag }}"\n'
            )
            wf_path.write_text(original, encoding='utf-8')

            res = gen.process_repository(repo_dir, apply=True, repo_name='MultilineYamlRepo')
            self.assertFalse(res.eligible_for_batch)
            self.assertFalse(res.applied)
            self.assertEqual([], res.changed_files)
            self.assertEqual(original, wf_path.read_text(encoding='utf-8'))
            self.assertTrue(
                any(w['kind'] == 'post_transform_residual_run' for w in res.warnings),
                f'Expected post_transform_residual_run warning, got {res.warnings}',
            )

            cli = subprocess.run(
                [sys.executable, '-B', str(SCRIPT_DIR / 'fix_workflow_steps_outputs_in_run.py'),
                 '--repo', str(repo_dir), '--dry-run'],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, cli.returncode)
            self.assertIn('post_transform_residual_run', cli.stdout)

    def test_c3_fail_closed_on_compound_expr_and_with_script_and_contract_rejects_with_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / 'UnsupportedRepo'
            wf_dir = repo_dir / '.github' / 'workflows'
            wf_dir.mkdir(parents=True)
            wf_path = wf_dir / 'deploy.yml'
            original = """name: Deploy
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Compound expr
        run: echo "${{ steps.a.outputs.x || steps.b.outputs.y }}"
      - name: Github script
        uses: actions/github-script@v7
        with:
          script: |
            console.log("${{ steps.ini.outputs.name }}")
"""
            wf_path.write_text(original, encoding='utf-8')

            # Generator must fail closed: skip repo, report both warnings, do not modify files.
            res = gen.process_repository(repo_dir, apply=True, repo_name='UnsupportedRepo')
            self.assertFalse(res.eligible_for_batch)
            self.assertFalse(res.applied)
            self.assertEqual([], res.changed_files)
            self.assertEqual(original, wf_path.read_text(encoding='utf-8'))
            kinds = {w['kind'] for w in res.warnings}
            self.assertEqual({'unsupported_compound_expression', 'unsupported_with_script'}, kinds)

            # CLI --dry-run must explicitly list with.script and exit != 0.
            cli = subprocess.run(
                [sys.executable, '-B', str(SCRIPT_DIR / 'fix_workflow_steps_outputs_in_run.py'),
                 '--repo', str(repo_dir), '--dry-run'],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, cli.returncode)
            self.assertIn('unsupported_with_script', cli.stdout)
            self.assertIn('steps.ini.outputs.name', cli.stdout)

            # Injected contract test must reject BOTH the compound run: expr and with.script.
            red = _run_contract_test(repo_dir)
            self.assertNotEqual(0, red.returncode)
            combined = red.stdout + red.stderr
            self.assertIn('with.script', combined)
            self.assertIn('steps.ini.outputs.name', combined)
            self.assertIn('steps.a.outputs.x || steps.b.outputs.y', combined)

    def test_invalid_yaml_exits_nonzero_without_python_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / 'BrokenYamlRepo'
            wf_dir = repo_dir / '.github' / 'workflows'
            wf_dir.mkdir(parents=True)
            (wf_dir / 'broken.yml').write_text(
                'name: Broken\non: push\njobs:\n  a:\n    steps: [\n',
                encoding='utf-8',
            )
            cli = subprocess.run(
                [sys.executable, '-B', str(SCRIPT_DIR / 'fix_workflow_steps_outputs_in_run.py'),
                 '--repo', str(repo_dir), '--dry-run'],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, cli.returncode)
            self.assertIn('Invalid YAML', cli.stderr)
            self.assertIn('broken.yml', cli.stderr)
            self.assertNotIn('Traceback', cli.stderr)

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

        self.assertEqual('${{ steps.ini.outputs.name }}', build_step['env']['PLUGIN_NAME'])
        self.assertEqual('${{ steps.ini.outputs.version }}', build_step['env']['PLUGIN_VERSION'])
        self.assertNotIn('steps.ini.outputs.name', build_step['run'])
        self.assertNotIn('steps.ini.outputs.version', build_step['run'])
        self.assertIn('"/tmp/${PLUGIN_NAME}-v${PLUGIN_VERSION}.zip"', build_step['run'])

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
            self.assertTrue(res.eligible_for_batch)
            self.assertGreater(res.diff_bytes, 0)
            after = (repo_dir / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')
            self.assertEqual(before, after)
            self.assertFalse((repo_dir / gen.CONTRACT_TEST_REL_PATH).exists())

    def test_contract_test_fallback_without_pyyaml_reports_with_script_label(self) -> None:
        namespace: dict[str, object] = {
            '__file__': str(SCRIPT_DIR / 'test_workflow_no_steps_outputs_in_run.py'),
            '__name__': 'test_workflow_no_steps_outputs_in_run',
        }
        exec(compile(gen.CONTRACT_TEST_SOURCE, 'test_workflow_no_steps_outputs_in_run.py', 'exec'), namespace)
        find_fallback = namespace['_find_fallback']
        assert callable(find_fallback)

        block_script_wf = """name: Unsafe Script
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Bad github-script
        uses: actions/github-script@v7
        with:
          script: |
            console.log("${{ steps.ini.outputs.name }}")
"""
        block_violations = find_fallback(block_script_wf, 'unsafe-script.yml')
        self.assertEqual(1, len(block_violations))
        self.assertIn('(with.script)', block_violations[0])
        self.assertIn('steps.ini.outputs.name', block_violations[0])

        inline_script_wf = """name: Unsafe Inline Script
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Bad inline github-script
        uses: actions/github-script@v7
        with:
          script: console.log("${{ steps.ini.outputs.version }}")
"""
        inline_violations = find_fallback(inline_script_wf, 'unsafe-inline-script.yml')
        self.assertEqual(1, len(inline_violations))
        self.assertIn('(with.script)', inline_violations[0])
        self.assertIn('steps.ini.outputs.version', inline_violations[0])

        # Also verify the generated unittest passes when PyYAML is unavailable (yaml = None).
        namespace['yaml'] = None
        test_cls = namespace['WorkflowNoStepsOutputsInRunTest']
        case = test_cls('test_detects_unsafe_interpolation_in_with_script')
        result = unittest.TestResult()
        case.run(result)
        self.assertTrue(
            result.wasSuccessful(),
            f'Expected test_detects_unsafe_interpolation_in_with_script to pass without PyYAML: '
            f'failures={result.failures}, errors={result.errors}',
        )

    def test_contract_test_full_suite_runs_with_yaml_none_and_covers_fallback_and_needs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = _copy_fixture('BeplyA3', Path(tmp))
            gen.process_repository(repo_dir, apply=True, repo_name='BeplyA3')
            test_file = repo_dir / gen.CONTRACT_TEST_REL_PATH

            # Run the ENTIRE generated contract test suite with yaml forced to None.
            namespace: dict[str, object] = {
                '__file__': str(test_file),
                '__name__': 'test_workflow_no_steps_outputs_in_run',
            }
            exec(compile(gen.CONTRACT_TEST_SOURCE, str(test_file), 'exec'), namespace)
            namespace['yaml'] = None
            suite = unittest.TestLoader().loadTestsFromTestCase(
                namespace['WorkflowNoStepsOutputsInRunTest']
            )
            result = unittest.TestResult()
            suite.run(result)
            self.assertTrue(
                result.wasSuccessful(),
                f'Full generated suite failed with yaml=None: '
                f'failures={result.failures}, errors={result.errors}',
            )
            self.assertGreaterEqual(result.testsRun, 8)

            # Verify documented known limits (C-d) are present in CONTRACT_TEST_SOURCE.
            for expected_doc in (
                '.github/workflows',
                'flow mappings',
                'anclas YAML',
                'format(',
                "steps['a'].outputs",
                'toJSON(steps)',
            ):
                self.assertIn(expected_doc, gen.CONTRACT_TEST_SOURCE)

    def test_contract_test_fallback_kills_all_five_mutants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = _copy_fixture('BeplyA3', Path(tmp))
            gen.process_repository(repo_dir, apply=True, repo_name='BeplyA3')
            test_file = repo_dir / gen.CONTRACT_TEST_REL_PATH

            mutants: list[tuple[str, str, str]] = [
                (
                    'M1_indent_lt_instead_of_le',
                    'if nxt_indent <= key_indent:',
                    'if nxt_indent < key_indent:',
                ),
                (
                    'M2_only_first_block_line',
                    "matches = STEPS_OUTPUTS_RE.findall('\\n'.join(block_lines))",
                    "matches = STEPS_OUTPUTS_RE.findall('\\n'.join(block_lines[:1]))",
                ),
                (
                    'M3_drop_dash_prefix_from_regex',
                    r"m = re.match(r'^(\s*(?:-\s+)?)(run|script)\s*:(.*)$', line)",
                    r"m = re.match(r'^(\s*)(run|script)\s*:(.*)$', line)",
                ),
                (
                    'M4_break_on_blank_line',
                    "if nxt.strip() == '':\n                block_lines.append(nxt)\n                j += 1\n                continue",
                    "if nxt.strip() == '':\n                break",
                ),
                (
                    'M5_emit_script_instead_of_with_script',
                    "key_label = 'with.script' if key_name == 'script' else key_name",
                    'key_label = key_name',
                ),
            ]

            for mutant_name, original_snippet, mutated_snippet in mutants:
                with self.subTest(mutant=mutant_name):
                    self.assertIn(
                        original_snippet,
                        gen.CONTRACT_TEST_SOURCE,
                        f'Original snippet not found for {mutant_name}',
                    )
                    mutated_src = gen.CONTRACT_TEST_SOURCE.replace(
                        original_snippet, mutated_snippet, 1
                    )
                    namespace: dict[str, object] = {
                        '__file__': str(test_file),
                        '__name__': f'mutated_{mutant_name}',
                    }
                    exec(compile(mutated_src, f'{mutant_name}.py', 'exec'), namespace)
                    namespace['yaml'] = None
                    suite = unittest.TestLoader().loadTestsFromTestCase(
                        namespace['WorkflowNoStepsOutputsInRunTest']
                    )
                    result = unittest.TestResult()
                    suite.run(result)
                    self.assertFalse(
                        result.wasSuccessful(),
                        f'Mutant {mutant_name} survived the fallback test suite!',
                    )

    def test_c_c_quotes_phpunit_config_without_quoting_targets(self) -> None:
        workflow = r"""name: Unit
on: push
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - name: Run phpunit
        run: |
          php vendor/bin/phpunit \
            -c ${{ steps.unit-targets.outputs.config }} \
            ${{ steps.unit-targets.outputs.targets }}
"""
        transformed = gen.transform_workflow_text(workflow)
        data = yaml.safe_load(transformed)
        step = data['jobs']['unit']['steps'][0]
        run_cmd = step['run']

        self.assertEqual('${{ steps.unit-targets.outputs.config }}', step['env']['PHPUNIT_CONFIG'])
        self.assertEqual('${{ steps.unit-targets.outputs.targets }}', step['env']['PHPUNIT_TARGETS'])
        self.assertIn('-c "${PHPUNIT_CONFIG}"', run_cmd)
        self.assertNotIn('-c ${PHPUNIT_CONFIG}', run_cmd)
        self.assertIn('${PHPUNIT_TARGETS}', run_cmd)
        self.assertNotIn('"${PHPUNIT_TARGETS}"', run_cmd)

        # Verify in bash: PHPUNIT_CONFIG with spaces stays 1 arg, PHPUNIT_TARGETS splits into 2 args.
        probe_script = (
            'args=()\n'
            'for a in -c "${PHPUNIT_CONFIG}" ${PHPUNIT_TARGETS}; do args+=("$a"); done\n'
            'printf "%s|" "${#args[@]}" "${args[@]}"\n'
        )
        probe = subprocess.run(
            ['bash', '-euo', 'pipefail', '-c', probe_script],
            env={'PHPUNIT_CONFIG': 'my dir/phpunit.xml', 'PHPUNIT_TARGETS': 'TestA.php TestB.php'},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual('4|-c|my dir/phpunit.xml|TestA.php|TestB.php|', probe.stdout)

        # Adversarial proof: unquoted PHPUNIT_CONFIG splits spaces (5 args); quoted PHPUNIT_TARGETS collapses targets (3 args).
        for bad_args, expected_not in (
            ('-c ${PHPUNIT_CONFIG} ${PHPUNIT_TARGETS}', '4|-c|my dir/phpunit.xml|TestA.php|TestB.php|'),
            ('-c "${PHPUNIT_CONFIG}" "${PHPUNIT_TARGETS}"', '4|-c|my dir/phpunit.xml|TestA.php|TestB.php|'),
        ):
            bad_probe = subprocess.run(
                [
                    'bash',
                    '-euo',
                    'pipefail',
                    '-c',
                    f'args=(); for a in {bad_args}; do args+=("$a"); done; printf "%s|" "${{#args[@]}}" "${{args[@]}}"',
                ],
                env={'PHPUNIT_CONFIG': 'my dir/phpunit.xml', 'PHPUNIT_TARGETS': 'TestA.php TestB.php'},
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotEqual(expected_not, bad_probe.stdout)

    def test_contract_test_kills_untrusted_context_mutants_in_both_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = _copy_fixture('BeplyA3', Path(tmp))
            gen.process_repository(repo_dir, apply=True, repo_name='BeplyA3')
            test_file = repo_dir / gen.CONTRACT_TEST_REL_PATH

            # Baseline: full suite passes in BOTH PyYAML and yaml=None modes with >=13 tests.
            for force_none in (False, True):
                ns: dict[str, object] = {
                    '__file__': str(test_file),
                    '__name__': f'baseline_none_{force_none}',
                }
                exec(compile(gen.CONTRACT_TEST_SOURCE, str(test_file), 'exec'), ns)
                if force_none:
                    ns['yaml'] = None
                suite = unittest.TestLoader().loadTestsFromTestCase(
                    ns['WorkflowNoStepsOutputsInRunTest']
                )
                res = unittest.TestResult()
                suite.run(res)
                self.assertTrue(
                    res.wasSuccessful(),
                    f'Baseline failed (yaml_none={force_none}): failures={res.failures}, errors={res.errors}',
                )
                self.assertGreaterEqual(res.testsRun, 13)

            # Mutants: removing each untrusted context pattern individually MUST fail in BOTH modes.
            context_mutants = (
                ('M_inputs', "    r'\\binputs\\.[A-Za-z0-9_.-]+',\n"),
                ('M_github_event', "    r'\\bgithub\\.event\\.[A-Za-z0-9_.-]+',\n"),
                ('M_github_head_ref', "    r'\\bgithub\\.head_ref\\b',\n"),
                ('M_github_base_ref', "    r'\\bgithub\\.base_ref\\b',\n"),
                ('M_github_ref_name', "    r'\\bgithub\\.ref_name\\b',\n"),
            )
            for mutant_name, pattern_line in context_mutants:
                self.assertIn(
                    pattern_line,
                    gen.CONTRACT_TEST_SOURCE,
                    f'Pattern line for {mutant_name} not found in CONTRACT_TEST_SOURCE',
                )
                mutated_src = gen.CONTRACT_TEST_SOURCE.replace(pattern_line, '', 1)
                for force_none in (False, True):
                    with self.subTest(mutant=mutant_name, yaml_none=force_none):
                        ns = {
                            '__file__': str(test_file),
                            '__name__': f'{mutant_name}_none_{force_none}',
                        }
                        exec(compile(mutated_src, f'{mutant_name}.py', 'exec'), ns)
                        if force_none:
                            ns['yaml'] = None
                        suite = unittest.TestLoader().loadTestsFromTestCase(
                            ns['WorkflowNoStepsOutputsInRunTest']
                        )
                        res = unittest.TestResult()
                        suite.run(res)
                        self.assertFalse(
                            res.wasSuccessful(),
                            f'Mutant {mutant_name} survived (yaml_none={force_none})!',
                        )

    def test_fail_closed_on_heredocs_and_non_posix_shells(self) -> None:
        cases = (
            (
                'heredoc_unquoted',
                'unsupported_heredoc_interpolation',
                """name: Heredoc Unquoted
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Write file with unquoted heredoc
        run: |
          cat <<EOF > version.txt
          version=${{ steps.ini.outputs.version }}
          EOF
""",
            ),
            (
                'heredoc_quoted',
                'unsupported_heredoc_interpolation',
                """name: Heredoc Quoted
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Write file with quoted heredoc
        run: |
          cat <<'EOF' > name.txt
          name=${{ steps.ini.outputs.name }}
          EOF
""",
            ),
            (
                'shell_python',
                'unsupported_non_posix_shell',
                """name: Python Shell
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Run python
        shell: python
        run: |
          print("${{ steps.ini.outputs.name }}")
""",
            ),
            (
                'shell_pwsh',
                'unsupported_non_posix_shell',
                """name: PowerShell
on: push
jobs:
  build:
    runs-on: windows-latest
    steps:
      - name: Run pwsh
        shell: pwsh
        run: |
          Write-Host "${{ steps.ini.outputs.version }}"
""",
            ),
        )

        for case_name, expected_kind, original in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / f'Repo_{case_name}'
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                wf_path = wf_dir / 'ci.yml'
                wf_path.write_text(original, encoding='utf-8')

                res = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertFalse(res.eligible_for_batch, f'{case_name} must fail closed')
                self.assertFalse(res.applied, f'{case_name} must not apply changes')
                self.assertEqual([], res.changed_files)
                self.assertEqual(original, wf_path.read_text(encoding='utf-8'))
                self.assertTrue(
                    any(w['kind'] == expected_kind for w in res.warnings),
                    f'Expected {expected_kind} for {case_name}, got {res.warnings}',
                )

                cli = subprocess.run(
                    [
                        sys.executable,
                        '-B',
                        str(SCRIPT_DIR / 'fix_workflow_steps_outputs_in_run.py'),
                        '--repo',
                        str(repo_dir),
                        '--dry-run',
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(0, cli.returncode, f'CLI must exit non-zero for {case_name}')
                self.assertIn(expected_kind, cli.stdout)

    def test_wire_contract_test_prefers_php84_compatibility_over_unit(self) -> None:
        tests_yml = """name: Tests
on: push
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Run phpunit
        run: vendor/bin/phpunit
  php84_compatibility:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Run PHP 8.4 scan
        run: php scripts/ci/php84-compat-scan.php "$PWD"
"""
        wired = gen.wire_contract_test_in_tests_yml(tests_yml)
        parsed = yaml.safe_load(wired)

        unit_steps = parsed['jobs']['unit']['steps']
        php84_steps = parsed['jobs']['php84_compatibility']['steps']

        self.assertFalse(
            any('test_workflow_no_steps_outputs_in_run.py' in str(s.get('run', '')) for s in unit_steps),
            'Contract test should not be wired into unit when php84_compatibility exists',
        )
        self.assertTrue(
            any('test_workflow_no_steps_outputs_in_run.py' in str(s.get('run', '')) for s in php84_steps),
            'Contract test must be wired into php84_compatibility',
        )
        # Idempotency check
        self.assertEqual(wired, gen.wire_contract_test_in_tests_yml(wired))


if __name__ == '__main__':
    unittest.main()
