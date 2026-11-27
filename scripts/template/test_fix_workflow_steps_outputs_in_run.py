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
                self.assertGreaterEqual(res.testsRun, 17)

            # Mutants: removing each untrusted context pattern individually MUST fail in BOTH modes.
            context_mutants = (
                ('M_inputs', "    r'\\binputs(?:\\.|\\[)|\\btoJSON\\s*\\(\\s*inputs\\s*\\)',\n"),
                ('M_github_event', "    r'\\bgithub\\.event\\b',\n"),
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

    def test_moves_inputs_github_event_and_refs_to_quoted_env_with_bash_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / 'PromoteRepo'
            wf_dir = repo_dir / '.github' / 'workflows'
            wf_dir.mkdir(parents=True)

            promote_prod = """name: Promote Production
on:
  workflow_dispatch:
    inputs:
      release_tag:
        required: true
        type: string
      dev_campaign_run_id:
        required: true
        type: string
      dev_campaign_run_url:
        required: true
        type: string
jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - name: Promote release
        run: |
          printf "tag=%s|run=%s|url=%s" ${{ inputs.release_tag }} "${{ inputs.dev_campaign_run_id }}" '${{ inputs.dev_campaign_run_url }}'
"""
            pr_notify = """name: PR Notify
on:
  pull_request:
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Print metadata
        run: |
          printf "%s|%s|%s|%s|%s" "${{ github.event.pull_request.title }}" ${{ github.event.inputs.target }} ${{ github.head_ref }} ${{ github.base_ref }} ${{ github.ref_name }}
"""
            (wf_dir / 'promote-production.yml').write_text(promote_prod, encoding='utf-8')
            (wf_dir / 'pr-notify.yml').write_text(pr_notify, encoding='utf-8')

            # RED before generator
            red = _run_contract_test(repo_dir)
            self.assertNotEqual(0, red.returncode)

            # CLI --dry-run must succeed (rc=0)
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
            self.assertEqual(0, cli.returncode, f'Expected rc=0 in dry-run:\n{cli.stdout}\n{cli.stderr}')

            # Apply generator
            res = gen.process_repository(repo_dir, apply=True, repo_name='PromoteRepo')
            self.assertTrue(res.eligible_for_batch)
            self.assertTrue(res.applied)
            self.assertEqual([], res.warnings)

            # Verify env: and quoted "${VAR}" in promote-production.yml
            p_data = yaml.safe_load((wf_dir / 'promote-production.yml').read_text(encoding='utf-8'))
            p_step = p_data['jobs']['promote']['steps'][0]
            self.assertEqual('${{ inputs.release_tag }}', p_step['env']['INPUT_RELEASE_TAG'])
            self.assertEqual('${{ inputs.dev_campaign_run_id }}', p_step['env']['INPUT_DEV_CAMPAIGN_RUN_ID'])
            self.assertEqual('${{ inputs.dev_campaign_run_url }}', p_step['env']['INPUT_DEV_CAMPAIGN_RUN_URL'])
            self.assertIn('"${INPUT_RELEASE_TAG}"', p_step['run'])
            self.assertIn('"${INPUT_DEV_CAMPAIGN_RUN_ID}"', p_step['run'])
            self.assertIn('"${INPUT_DEV_CAMPAIGN_RUN_URL}"', p_step['run'])

            # Real bash proof: malicious inputs.release_tag='v1.0$(id)' is literal data, never executed.
            probe_p = subprocess.run(
                ['bash', '-euo', 'pipefail', '-c', p_step['run']],
                env={
                    'INPUT_RELEASE_TAG': 'v1.0$(id)',
                    'INPUT_DEV_CAMPAIGN_RUN_ID': '12345',
                    'INPUT_DEV_CAMPAIGN_RUN_URL': 'https://example.test/runs/12345',
                },
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                'tag=v1.0$(id)|run=12345|url=https://example.test/runs/12345',
                probe_p.stdout,
            )

            # Verify env: and quoted "${VAR}" in pr-notify.yml
            n_data = yaml.safe_load((wf_dir / 'pr-notify.yml').read_text(encoding='utf-8'))
            n_step = n_data['jobs']['notify']['steps'][0]
            self.assertEqual(
                '${{ github.event.pull_request.title }}',
                n_step['env']['GH_EVENT_PULL_REQUEST_TITLE'],
            )
            self.assertEqual(
                '${{ github.event.inputs.target }}',
                n_step['env']['GH_EVENT_INPUTS_TARGET'],
            )
            self.assertEqual('${{ github.head_ref }}', n_step['env']['GITHUB_HEAD_REF'])
            self.assertEqual('${{ github.base_ref }}', n_step['env']['GITHUB_BASE_REF'])
            self.assertEqual('${{ github.ref_name }}', n_step['env']['GITHUB_REF_NAME'])
            self.assertIn('"${GH_EVENT_PULL_REQUEST_TITLE}"', n_step['run'])
            self.assertIn('"${GH_EVENT_INPUTS_TARGET}"', n_step['run'])
            self.assertIn('"${GITHUB_HEAD_REF}"', n_step['run'])
            self.assertIn('"${GITHUB_BASE_REF}"', n_step['run'])
            self.assertIn('"${GITHUB_REF_NAME}"', n_step['run'])

            probe_n = subprocess.run(
                ['bash', '-euo', 'pipefail', '-c', n_step['run']],
                env={
                    'GH_EVENT_PULL_REQUEST_TITLE': 'feat: $(id)',
                    'GH_EVENT_INPUTS_TARGET': 'prod$(uname)',
                    'GITHUB_HEAD_REF': 'feat/x',
                    'GITHUB_BASE_REF': 'main',
                    'GITHUB_REF_NAME': 'v1.0.0',
                },
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual('feat: $(id)|prod$(uname)|feat/x|main|v1.0.0', probe_n.stdout)

            # Idempotency: 2nd pass yields 0 diff
            second = gen.process_repository(repo_dir, apply=True, repo_name='PromoteRepo')
            self.assertEqual([], second.changed_files)
            self.assertEqual(0, second.diff_bytes)

            # Injected contract test passes 100% GREEN in BOTH PyYAML and yaml=None modes
            green = _run_contract_test(repo_dir)
            self.assertEqual(0, green.returncode, f'Contract test failed:\n{green.stdout}\n{green.stderr}')
            test_file = repo_dir / gen.CONTRACT_TEST_REL_PATH
            for force_none in (False, True):
                ns: dict[str, object] = {
                    '__file__': str(test_file),
                    '__name__': f'promote_contract_none_{force_none}',
                }
                exec(compile(gen.CONTRACT_TEST_SOURCE, str(test_file), 'exec'), ns)
                if force_none:
                    ns['yaml'] = None
                suite = unittest.TestLoader().loadTestsFromTestCase(
                    ns['WorkflowNoStepsOutputsInRunTest']
                )
                suite_res = unittest.TestResult()
                suite.run(suite_res)
                self.assertTrue(
                    suite_res.wasSuccessful(),
                    f'Contract suite failed (yaml_none={force_none}): '
                    f'failures={suite_res.failures}, errors={suite_res.errors}',
                )

    def test_fail_closed_on_unrewritable_inputs_and_github_event_forms(self) -> None:
        cases = (
            (
                'heredoc_inputs',
                'unsupported_heredoc_interpolation',
                """name: Heredoc Inputs
on: workflow_dispatch
jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - name: Write tag
        run: |
          cat <<EOF > tag.txt
          ${{ inputs.release_tag }}
          EOF
""",
            ),
            (
                'shell_python_inputs',
                'unsupported_non_posix_shell',
                """name: Python Inputs
on: workflow_dispatch
jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - name: Print tag
        shell: python
        run: print("${{ inputs.release_tag }}")
""",
            ),
            (
                'shell_pwsh_event',
                'unsupported_non_posix_shell',
                """name: Pwsh Event
on: pull_request
jobs:
  notify:
    runs-on: windows-latest
    steps:
      - name: Print title
        shell: pwsh
        run: Write-Host "${{ github.event.pull_request.title }}"
""",
            ),
            (
                'tojson_github_event',
                'unsupported_compound_expression',
                """name: ToJSON Event
on: pull_request
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Dump event
        run: echo "${{ toJSON(github.event) }}"
""",
            ),
            (
                'format_github_event',
                'unsupported_compound_expression',
                """name: Format Event
on: pull_request
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Format title
        run: echo "${{ format('{0}', github.event.pull_request.title) }}"
""",
            ),
            (
                'with_script_inputs',
                'unsupported_with_script',
                """name: Script Inputs
on: workflow_dispatch
jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - name: Github script
        uses: actions/github-script@v7
        with:
          script: |
            console.log("${{ inputs.release_tag }}")
""",
            ),
        )
        for case_name, expected_kind, original in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / f'FailClosed_{case_name}'
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                wf_path = wf_dir / 'ci.yml'
                wf_path.write_text(original, encoding='utf-8')

                res = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertFalse(res.eligible_for_batch, f'{case_name} must fail closed')
                self.assertFalse(res.applied)
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

    def test_adversarial_mutants_not_moving_inputs_or_github_event_fail(self) -> None:
        from unittest import mock

        cases = (
            (
                'mutant_no_inputs',
                r'\$\{\{\s*(steps\.[A-Za-z0-9_-]+\.outputs\.[A-Za-z0-9_-]+|github\.event\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*|github\.(?:head_ref|base_ref|ref_name))\s*\}\}',
                """name: Promote
on: workflow_dispatch
jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - name: Promote
        run: echo "${{ inputs.release_tag }}"
""",
            ),
            (
                'mutant_no_github_event',
                r'\$\{\{\s*(steps\.[A-Za-z0-9_-]+\.outputs\.[A-Za-z0-9_-]+|inputs\.[A-Za-z0-9_-]+|github\.(?:head_ref|base_ref|ref_name))\s*\}\}',
                """name: Notify
on: pull_request
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Notify
        run: echo "${{ github.event.pull_request.title }}"
""",
            ),
        )
        import re as _re

        for mutant_name, mutated_pattern, wf_text in cases:
            with self.subTest(mutant=mutant_name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / mutant_name
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                (wf_dir / 'ci.yml').write_text(wf_text, encoding='utf-8')

                with mock.patch.object(gen, 'SIMPLE_UNTRUSTED_EXPR_RE', _re.compile(mutated_pattern)):
                    res = gen.process_repository(repo_dir, apply=True, repo_name=mutant_name)
                    # Mutant fails to rewrite -> generator fails closed and contract test stays RED
                    self.assertFalse(res.eligible_for_batch)
                    red = _run_contract_test(repo_dir)
                    self.assertNotEqual(0, red.returncode)

    def test_c1_fail_closed_on_shell_eval_sinks_generator_and_contract(self) -> None:
        sink_cases = (
            ('eval', 'eval "echo ${{ inputs.x }}"', 'eval "echo ${INPUT_X}"'),
            ('bash_c', 'bash -c "echo ${{ inputs.x }}"', 'bash -c "echo ${INPUT_X}"'),
            ('sh_c', "sh -c 'echo ${{ inputs.x }}'", 'sh -lc "echo ${INPUT_X}"'),
            ('zsh_c', 'zsh -c "echo ${{ inputs.x }}"', 'zsh -c "echo ${INPUT_X}"'),
            ('dash_c', 'dash -ec "echo ${{ inputs.x }}"', 'dash -ec "echo ${INPUT_X}"'),
            ('ssh', 'ssh deploy@host "echo ${{ inputs.x }}"', 'ssh deploy@host "echo ${INPUT_X}"'),
            ('su_c', 'su -s /bin/sh www-data -c "echo ${{ inputs.x }}"', 'su -s /bin/sh www-data -c "echo ${INPUT_X}"'),
            ('xargs_sh', 'printf "%s\\n" "${{ inputs.x }}" | xargs bash', 'printf "%s\\n" "${INPUT_X}" | xargs bash'),
        )

        for sink_name, raw_cmd, env_cmd in sink_cases:
            with self.subTest(sink=sink_name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / f'Sink_{sink_name}'
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)

                # 1. Generator must fail closed with unsupported_shell_eval_sink
                raw_wf = f"""name: Sink {sink_name}
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Sink step
        run: |
          {raw_cmd}
"""
                wf_path = wf_dir / 'sink.yml'
                wf_path.write_text(raw_wf, encoding='utf-8')
                res = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertFalse(res.eligible_for_batch, f'Generator must fail closed on {sink_name}')
                self.assertFalse(res.applied)
                self.assertEqual(raw_wf, wf_path.read_text(encoding='utf-8'))
                self.assertTrue(
                    any(w['kind'] == 'unsupported_shell_eval_sink' for w in res.warnings),
                    f'Expected unsupported_shell_eval_sink for {sink_name}, got {res.warnings}',
                )

                # 2. Contract test must ALSO reject env-mapped untrusted var passed to sink in BOTH modes
                env_wf = f"""name: Env Sink {sink_name}
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Env sink step
        env:
          INPUT_X: ${{{{ inputs.x }}}}
        run: |
          {env_cmd}
"""
                ns: dict[str, object] = {
                    '__file__': str(repo_dir / gen.CONTRACT_TEST_REL_PATH),
                    '__name__': f'contract_sink_{sink_name}',
                }
                exec(compile(gen.CONTRACT_TEST_SOURCE, 'contract.py', 'exec'), ns)
                v_yaml = ns['_find_with_pyyaml'](env_wf, f'{sink_name}.yml')
                v_fb = ns['_find_fallback'](env_wf, f'{sink_name}.yml')
                self.assertEqual(1, len(v_yaml), f'PyYAML contract missed {sink_name}: {v_yaml}')
                self.assertEqual(1, len(v_fb), f'Fallback contract missed {sink_name}: {v_fb}')
                self.assertIn('shell-eval-sink', v_yaml[0])
                self.assertIn('shell-eval-sink', v_fb[0])

        # Adversarial mutant check: removing any of the 5 sink patterns from CONTRACT_TEST_SOURCE
        # must cause test_rejects_untrusted_env_in_shell_eval_sinks to FAIL in BOTH modes.
        sink_mutants = (
            ('M_sink_eval', "    r'(?:^|[;|&(`]|\\s)eval(?:\\s|$)',\n"),
            ('M_sink_shell_c', "    r'(?:^|[;|&(`]|\\s)(?:/[^\\s;|&]*?/)?(?:bash|sh|zsh|dash)\\b[^#\\n;|&]*\\s-[a-zA-Z]*c\\b',\n"),
            ('M_sink_ssh', "    r'(?:^|[;|&(`]|\\s)(?:/[^\\s;|&]*?/)?ssh(?:\\s|$)',\n"),
            ('M_sink_su_c', "    r'(?:^|[;|&(`]|\\s)(?:/[^\\s;|&]*?/)?su\\b[^#\\n;|&]*\\s-[a-zA-Z]*c\\b',\n"),
            ('M_sink_xargs_sh', "    r'(?:^|[;|&(`]|\\s)(?:/[^\\s;|&]*?/)?xargs\\b[^#\\n;|&]*\\s(?:/[^\\s;|&]*?/)?(?:bash|sh|zsh|dash)\\b',\n"),
        )
        for m_name, pat_line in sink_mutants:
            self.assertIn(pat_line, gen.CONTRACT_TEST_SOURCE, f'{m_name} pattern not found')
            mut_src = gen.CONTRACT_TEST_SOURCE.replace(pat_line, '', 1)
            for force_none in (False, True):
                with self.subTest(mutant=m_name, yaml_none=force_none):
                    ns = {'__file__': 'scripts/ci/test_workflow_no_steps_outputs_in_run.py', '__name__': m_name}
                    exec(compile(mut_src, f'{m_name}.py', 'exec'), ns)
                    if force_none:
                        ns['yaml'] = None
                    case = ns['WorkflowNoStepsOutputsInRunTest']('test_rejects_untrusted_env_in_shell_eval_sinks')
                    r = unittest.TestResult()
                    case.run(r)
                    self.assertFalse(r.wasSuccessful(), f'Sink mutant {m_name} survived (yaml_none={force_none})!')

    def test_c2_gh_event_prefix_and_reserved_runner_env_guard(self) -> None:
        from unittest import mock

        safe_wf = """name: Event Names
on: push
jobs:
  meta:
    runs-on: ubuntu-latest
    steps:
      - name: Print event fields
        run: |
          printf "%s|%s|%s" ${{ github.event.name }} ${{ github.event.path }} ${{ github.head_ref }}
"""
        transformed, warnings = gen.analyze_and_transform_workflow_text(safe_wf, 'meta.yml')
        self.assertEqual([], warnings)
        data = yaml.safe_load(transformed)
        step = data['jobs']['meta']['steps'][0]
        self.assertEqual('${{ github.event.name }}', step['env']['GH_EVENT_NAME'])
        self.assertEqual('${{ github.event.path }}', step['env']['GH_EVENT_PATH'])
        self.assertEqual('${{ github.head_ref }}', step['env']['GITHUB_HEAD_REF'])
        self.assertNotIn('GITHUB_EVENT_NAME', step['env'])
        self.assertNotIn('GITHUB_EVENT_PATH', step['env'])

        # Reserved runner env collisions MUST fail closed
        reserved_cases = (
            ('runner_prefix', 'steps.runner_attestation.outputs.os', 'RUNNER_ATTESTATION_OS'),
            ('actions_prefix', 'steps.actions_attestation.outputs.id', 'ACTIONS_ATTESTATION_ID'),
            ('github_prefix', 'steps.github_attestation.outputs.sha', 'GITHUB_ATTESTATION_SHA'),
        )
        for case_name, expr, expected_var in reserved_cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / f'Reserved_{case_name}'
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                wf_text = f"""name: Reserved {case_name}
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Collide
        run: echo "${{{{ {expr} }}}}"
"""
                wf_path = wf_dir / 'ci.yml'
                wf_path.write_text(wf_text, encoding='utf-8')
                res = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertFalse(res.eligible_for_batch)
                self.assertFalse(res.applied)
                self.assertEqual(wf_text, wf_path.read_text(encoding='utf-8'))
                self.assertTrue(
                    any(
                        w['kind'] == 'reserved_runner_env_name' and w.get('env_name') == expected_var
                        for w in res.warnings
                    ),
                    f'Expected reserved_runner_env_name ({expected_var}), got {res.warnings}',
                )

        # Also verify exact reserved name 'CI' fails closed
        ci_wf = """name: Reserved CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Collide CI
        run: echo "${{ inputs.ci }}"
"""
        with mock.patch.object(gen, '_canonical_env_name_for_expr', return_value='CI'):
            _, ci_warnings = gen.analyze_and_transform_workflow_text(ci_wf, 'ci.yml')
            self.assertTrue(
                any(
                    w['kind'] == 'reserved_runner_env_name' and w.get('env_name') == 'CI'
                    for w in ci_warnings
                ),
                f'Expected reserved_runner_env_name for CI, got {ci_warnings}',
            )

    def test_c3_workflow_and_job_level_env_sinks_detected_in_both_modes(self) -> None:
        wf_env = """name: Workflow Env Sink
on: workflow_dispatch
env:
  WF_X: ${{ inputs.x }}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Eval workflow env
        run: |
          eval "echo $WF_X"
"""
        job_env = """name: Job Env Sink
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      JOB_X: ${{ inputs.y }}
    steps:
      - name: Eval job env
        run: |
          eval "echo $JOB_X"
"""
        ns: dict[str, object] = {
            '__file__': 'scripts/ci/test_workflow_no_steps_outputs_in_run.py',
            '__name__': 'c3_env_scope',
        }
        exec(compile(gen.CONTRACT_TEST_SOURCE, 'contract.py', 'exec'), ns)

        for label, wf_text, expected_var in (
            ('workflow_env', wf_env, 'WF_X'),
            ('job_env', job_env, 'JOB_X'),
        ):
            for mode, fn in (('pyyaml', ns['_find_with_pyyaml']), ('fallback', ns['_find_fallback'])):
                with self.subTest(scope=label, mode=mode):
                    violations = fn(wf_text, f'{label}.yml')
                    self.assertEqual(1, len(violations), f'{label} ({mode}) missed sink: {violations}')
                    self.assertIn('shell-eval-sink', violations[0])
                    self.assertIn(expected_var, violations[0])

    def test_c4_kills_three_remaining_mutants_su_abspath_and_env_scopes(self) -> None:
        from unittest import mock
        import re as _re

        # 1. Mutant: remove su -c from generator SHELL_EVAL_SINK_PATTERNS
        su_wf = """name: Su Sink
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Su step
        run: su www-data -c "echo ${{ inputs.x }}"
"""
        _, base_warnings = gen.analyze_and_transform_workflow_text(su_wf, 'su.yml')
        self.assertTrue(any(w['kind'] == 'unsupported_shell_eval_sink' for w in base_warnings))

        no_su_patterns = [p for p in gen.SHELL_EVAL_SINK_PATTERNS if 'su\\b' not in p]
        self.assertEqual(len(gen.SHELL_EVAL_SINK_PATTERNS) - 1, len(no_su_patterns))
        with mock.patch.object(gen, 'SHELL_EVAL_SINK_RE', _re.compile('|'.join(no_su_patterns))):
            _, mut_warnings = gen.analyze_and_transform_workflow_text(su_wf, 'su.yml')
            self.assertFalse(any(w['kind'] == 'unsupported_shell_eval_sink' for w in mut_warnings))

        # 2. Mutant: remove absolute path prefix from bash/sh -c in BOTH generator and contract
        abs_raw_wf = """name: Abs Path Sink
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Abs bash
        run: /bin/bash -c "echo ${{ inputs.x }}"
"""
        _, abs_warnings = gen.analyze_and_transform_workflow_text(abs_raw_wf, 'abs.yml')
        self.assertTrue(any(w['kind'] == 'unsupported_shell_eval_sink' for w in abs_warnings))

        no_abs_gen_patterns = [p.replace(r'(?:/[^\s;|&]*?/)?', '') for p in gen.SHELL_EVAL_SINK_PATTERNS]
        with mock.patch.object(gen, 'SHELL_EVAL_SINK_RE', _re.compile('|'.join(no_abs_gen_patterns))):
            _, mut_abs_warnings = gen.analyze_and_transform_workflow_text(abs_raw_wf, 'abs.yml')
            self.assertFalse(any(w['kind'] == 'unsupported_shell_eval_sink' for w in mut_abs_warnings))

        abs_pat_literal = r'(?:/[^\s;|&]*?/)?'
        self.assertIn(abs_pat_literal, gen.CONTRACT_TEST_SOURCE)
        mut_contract_no_abs = gen.CONTRACT_TEST_SOURCE.replace(abs_pat_literal, '')
        for force_none in (False, True):
            with self.subTest(mutant='no_abs_path_contract', yaml_none=force_none):
                ns: dict[str, object] = {
                    '__file__': 'scripts/ci/test_workflow_no_steps_outputs_in_run.py',
                    '__name__': f'mut_no_abs_{force_none}',
                }
                exec(compile(mut_contract_no_abs, 'mut_no_abs.py', 'exec'), ns)
                if force_none:
                    ns['yaml'] = None
                case = ns['WorkflowNoStepsOutputsInRunTest']('test_rejects_untrusted_env_in_shell_eval_sinks')
                r = unittest.TestResult()
                case.run(r)
                self.assertFalse(r.wasSuccessful(), f'no_abs_path mutant survived (yaml_none={force_none})')

        # 3. Mutant: ignore workflow_env or job_env in contract (PyYAML + fallback)
        for scope_name, orig_snip, mut_snip in (
            ('pyyaml_ignore_workflow_env', 'merged_env = {**workflow_env, **job_env, **step_env}', 'merged_env = {**job_env, **step_env}'),
            ('pyyaml_ignore_job_env', 'merged_env = {**workflow_env, **job_env, **step_env}', 'merged_env = {**workflow_env, **step_env}'),
        ):
            self.assertIn(orig_snip, gen.CONTRACT_TEST_SOURCE)
            mut_src = gen.CONTRACT_TEST_SOURCE.replace(orig_snip, mut_snip, 1)
            with self.subTest(mutant=scope_name):
                ns = {'__file__': 'scripts/ci/test_workflow_no_steps_outputs_in_run.py', '__name__': scope_name}
                exec(compile(mut_src, f'{scope_name}.py', 'exec'), ns)
                case = ns['WorkflowNoStepsOutputsInRunTest']('test_rejects_untrusted_env_in_shell_eval_sinks')
                r = unittest.TestResult()
                case.run(r)
                self.assertFalse(r.wasSuccessful(), f'{scope_name} mutant survived!')

    def test_c5_new_shell_sinks_pipe_herestring_source_and_multiline_backslash(self) -> None:
        cases = (
            ('pipe_sh', 'echo "${{ inputs.x }}" | sh', 'echo "${INPUT_X}" | sh'),
            ('pipe_abs_bash', 'echo "${{ inputs.x }}" | /bin/bash', 'echo "${INPUT_X}" | /bin/bash'),
            ('herestring_bash', 'bash <<< "${{ inputs.x }}"', 'bash <<< "${INPUT_X}"'),
            ('source_procsub', 'source <(echo "${{ inputs.x }}")', 'source <(echo "${INPUT_X}")'),
            ('dot_procsub', '. <(echo "${{ inputs.x }}")', '. <(echo "${INPUT_X}")'),
            (
                'multiline_bash_c',
                'bash -c \\\n            "echo ${{ inputs.x }}"',
                'bash -c \\\n            "echo ${INPUT_X}"',
            ),
        )
        for name, raw_cmd, env_cmd in cases:
            with self.subTest(sink=name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / f'C5_{name}'
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                raw_wf = f"""name: C5 {name}
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Sink {name}
        run: |
          {raw_cmd}
"""
                wf_path = wf_dir / 'c5.yml'
                wf_path.write_text(raw_wf, encoding='utf-8')
                res = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertFalse(res.eligible_for_batch, f'Generator must fail closed on {name}')
                self.assertTrue(
                    any(w['kind'] == 'unsupported_shell_eval_sink' for w in res.warnings),
                    f'Expected unsupported_shell_eval_sink for {name}, got {res.warnings}',
                )

                env_wf = f"""name: C5 Env {name}
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Env Sink {name}
        env:
          INPUT_X: ${{{{ inputs.x }}}}
        run: |
          {env_cmd}
"""
                ns: dict[str, object] = {
                    '__file__': str(repo_dir / gen.CONTRACT_TEST_REL_PATH),
                    '__name__': f'c5_contract_{name}',
                }
                exec(compile(gen.CONTRACT_TEST_SOURCE, 'contract.py', 'exec'), ns)
                v_yaml = ns['_find_with_pyyaml'](env_wf, f'{name}.yml')
                v_fb = ns['_find_fallback'](env_wf, f'{name}.yml')
                self.assertEqual(1, len(v_yaml), f'PyYAML missed {name}: {v_yaml}')
                self.assertEqual(1, len(v_fb), f'Fallback missed {name}: {v_fb}')

        # Verify interpreter limits documented in CONTRACT_TEST_SOURCE
        for doc_token in ('python3 -c', 'node -e', 'awk'):
            self.assertIn(doc_token, gen.CONTRACT_TEST_SOURCE)

    def test_c6_generator_adds_pycache_and_pyc_to_gitignore_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = _copy_fixture('BeplyA3', Path(tmp))
            gi_path = repo_dir / '.gitignore'
            gi_path.write_text('vendor/\n', encoding='utf-8')

            first = gen.process_repository(repo_dir, apply=True, repo_name='BeplyA3')
            self.assertTrue(first.eligible_for_batch)
            self.assertIn('.gitignore', first.changed_files)
            gi_after = gi_path.read_text(encoding='utf-8')
            self.assertIn('__pycache__/', gi_after)
            self.assertIn('*.pyc', gi_after)
            self.assertIn('vendor/', gi_after)

            # 2nd pass must be idempotent (diff = 0)
            second = gen.process_repository(repo_dir, apply=True, repo_name='BeplyA3')
            self.assertEqual([], second.changed_files)
            self.assertEqual(0, second.diff_bytes)

            # Pre-existing .pyc under scripts/ci must fail closed
            pyc_file = repo_dir / 'scripts' / 'ci' / '__pycache__' / 'stale.pyc'
            pyc_file.parent.mkdir(parents=True, exist_ok=True)
            pyc_file.write_bytes(b'\x00')
            dirty = gen.process_repository(repo_dir, apply=True, repo_name='BeplyA3')
            self.assertFalse(dirty.eligible_for_batch)
            self.assertTrue(any(w['kind'] == 'unclean_pyc_artifacts' for w in dirty.warnings))

    def test_rewrites_env_context_in_run_without_duplicating_env_and_kills_mutant(self) -> None:
        from unittest import mock
        import re as _re

        wf_text = """name: Tests
on: push
env:
  PLUGIN_FOLDER: ${{ github.event.repository.name }}
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Prepare ARC PHP prerequisites
        run: |
          echo ${{ env.PLUGIN_FOLDER }}
          test -d "Plugins/${{ env.PLUGIN_FOLDER }}"
          printf "%s" '${{ env.PLUGIN_FOLDER }}'
"""
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / 'EnvContextRepo'
            wf_dir = repo_dir / '.github' / 'workflows'
            wf_dir.mkdir(parents=True)
            wf_path = wf_dir / 'tests.yml'
            wf_path.write_text(wf_text, encoding='utf-8')

            # RED before generator
            red = _run_contract_test(repo_dir)
            self.assertNotEqual(0, red.returncode)

            res = gen.process_repository(repo_dir, apply=True, repo_name='EnvContextRepo')
            self.assertTrue(res.eligible_for_batch)
            self.assertTrue(res.applied)
            self.assertEqual([], res.warnings)

            parsed = yaml.safe_load(wf_path.read_text(encoding='utf-8'))
            step = parsed['jobs']['lint']['steps'][0]
            self.assertNotIn('env', step, 'Rewriting ${{ env.X }} must not duplicate step env:')
            self.assertIn('echo "${PLUGIN_FOLDER}"', step['run'])
            self.assertIn('test -d "Plugins/${PLUGIN_FOLDER}"', step['run'])
            self.assertIn('printf "%s" "${PLUGIN_FOLDER}"', step['run'])
            self.assertNotIn('env.PLUGIN_FOLDER', step['run'])

            # Idempotency
            second = gen.process_repository(repo_dir, apply=True, repo_name='EnvContextRepo')
            self.assertEqual([], second.changed_files)
            self.assertEqual(0, second.diff_bytes)

            # Contract test passes in BOTH PyYAML and yaml=None modes
            test_file = repo_dir / gen.CONTRACT_TEST_REL_PATH
            for force_none in (False, True):
                ns: dict[str, object] = {
                    '__file__': str(test_file),
                    '__name__': f'env_contract_none_{force_none}',
                }
                exec(compile(gen.CONTRACT_TEST_SOURCE, str(test_file), 'exec'), ns)
                if force_none:
                    ns['yaml'] = None
                suite = unittest.TestLoader().loadTestsFromTestCase(
                    ns['WorkflowNoStepsOutputsInRunTest']
                )
                r = unittest.TestResult()
                suite.run(r)
                self.assertTrue(r.wasSuccessful(), f'Failed (yaml_none={force_none}): {r.failures} {r.errors}')

        # Fail-closed on env.X in heredoc, non-POSIX shell, and eval sink
        for kind_name, expected_kind, bad_wf in (
            (
                'env_heredoc',
                'unsupported_heredoc_interpolation',
                'name: H\non: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n          cat <<EOF\n          ${{ env.PLUGIN_FOLDER }}\n          EOF\n',
            ),
            (
                'env_python',
                'unsupported_non_posix_shell',
                'name: P\non: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - shell: python\n        run: print("${{ env.PLUGIN_FOLDER }}")\n',
            ),
            (
                'env_eval',
                'unsupported_shell_eval_sink',
                'name: E\non: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - run: eval "echo ${{ env.PLUGIN_FOLDER }}"\n',
            ),
        ):
            with self.subTest(fail_closed=kind_name):
                _, w = gen.analyze_and_transform_workflow_text(bad_wf, f'{kind_name}.yml')
                self.assertTrue(any(x['kind'] == expected_kind for x in w), f'{kind_name}: {w}')

        # Adversarial mutant: removing env pattern from CONTRACT_TEST_SOURCE must fail in BOTH modes
        env_pat_line = "    r'\\benv(?:\\.|\\[)|\\btoJSON\\s*\\(\\s*env\\s*\\)',\n"
        self.assertIn(env_pat_line, gen.CONTRACT_TEST_SOURCE)
        mut_src = gen.CONTRACT_TEST_SOURCE.replace(env_pat_line, '', 1)
        for force_none in (False, True):
            with self.subTest(mutant='M_env_context', yaml_none=force_none):
                ns = {'__file__': 'scripts/ci/test_workflow_no_steps_outputs_in_run.py', '__name__': 'm_env'}
                exec(compile(mut_src, 'm_env.py', 'exec'), ns)
                if force_none:
                    ns['yaml'] = None
                case = ns['WorkflowNoStepsOutputsInRunTest']('test_detects_env_context')
                r = unittest.TestResult()
                case.run(r)
                self.assertFalse(r.wasSuccessful(), f'M_env_context survived (yaml_none={force_none})')

        # Adversarial mutant: generator not rewriting env.* fails closed
        no_env_re = _re.compile(gen.SIMPLE_UNTRUSTED_EXPR_RE.pattern.replace(r'|env\.[A-Za-z_][A-Za-z0-9_]*', ''))
        with mock.patch.object(gen, 'SIMPLE_UNTRUSTED_EXPR_RE', no_env_re):
            _, mw = gen.analyze_and_transform_workflow_text(wf_text, 'tests.yml')
            self.assertTrue(len(mw) > 0, 'Generator mutant ignoring env.* must fail closed')

    def test_c1_env_rewrite_requires_exact_case_static_definition_and_kills_upper_mutant(self) -> None:
        from unittest import mock

        # Case 1: undefined env vars (HOME, GITHUB_SHA) MUST fail closed
        for label, expr in (
            ('undefined_HOME', '${{ env.HOME }}'),
            ('undefined_GITHUB_SHA', '${{ env.GITHUB_SHA }}'),
        ):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / label
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                wf_text = f"""name: Undefined Env
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Print undefined env
        run: echo "{expr}"
"""
                wf_path = wf_dir / 'ci.yml'
                wf_path.write_text(wf_text, encoding='utf-8')
                res = gen.process_repository(repo_dir, apply=True, repo_name=label)
                self.assertFalse(res.eligible_for_batch, f'{label} must fail closed')
                self.assertFalse(res.applied)
                self.assertEqual(wf_text, wf_path.read_text(encoding='utf-8'))
                self.assertTrue(
                    any(w['kind'] == 'undefined_or_case_mismatched_env_var' for w in res.warnings),
                    f'Expected undefined_or_case_mismatched_env_var for {label}, got {res.warnings}',
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
                self.assertNotEqual(0, cli.returncode)

        # Case 2: case-mismatched env var (WF defined, env.wf referenced) MUST fail closed
        case_mismatch_wf = """name: Case Mismatch
on: push
env:
  WF: foo
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Print lower wf
        run: echo "${{ env.wf }}"
"""
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / 'CaseMismatch'
            wf_dir = repo_dir / '.github' / 'workflows'
            wf_dir.mkdir(parents=True)
            wf_path = wf_dir / 'ci.yml'
            wf_path.write_text(case_mismatch_wf, encoding='utf-8')

            res = gen.process_repository(repo_dir, apply=True, repo_name='CaseMismatch')
            self.assertFalse(res.eligible_for_batch, 'env.wf with only WF defined must fail closed')
            self.assertFalse(res.applied)
            self.assertEqual(case_mismatch_wf, wf_path.read_text(encoding='utf-8'))
            self.assertTrue(
                any(
                    w['kind'] == 'undefined_or_case_mismatched_env_var' and w.get('env_name') == 'wf'
                    for w in res.warnings
                ),
                f'Expected undefined_or_case_mismatched_env_var (wf), got {res.warnings}',
            )

            # Reviewer's .upper() mutant: case-insensitive comparison would wrongly mark it eligible!
            with mock.patch.object(
                gen,
                '_env_var_defined_in_scope',
                side_effect=lambda name, defined: name.upper() in {d.upper() for d in defined},
            ):
                mut_res = gen.process_repository(repo_dir, apply=False, repo_name='CaseMismatch')
                self.assertTrue(mut_res.eligible_for_batch, '.upper() mutant should wrongly accept case mismatch')

        # Good case: PLUGIN_FOLDER defined at workflow, job, OR step level rewrites cleanly & idempotently
        for scope_name, good_wf in (
            (
                'workflow_level',
                'name: T\non: push\nenv:\n  PLUGIN_FOLDER: Demo\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ${{ env.PLUGIN_FOLDER }}\n',
            ),
            (
                'job_level',
                'name: T\non: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    env:\n      PLUGIN_FOLDER: Demo\n    steps:\n      - run: echo ${{ env.PLUGIN_FOLDER }}\n',
            ),
            (
                'step_level',
                'name: T\non: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - env:\n          PLUGIN_FOLDER: Demo\n        run: echo ${{ env.PLUGIN_FOLDER }}\n',
            ),
        ):
            with self.subTest(good_scope=scope_name), tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / f'Good_{scope_name}'
                wf_dir = repo_dir / '.github' / 'workflows'
                wf_dir.mkdir(parents=True)
                wf_path = wf_dir / 'ci.yml'
                wf_path.write_text(good_wf, encoding='utf-8')
                r1 = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertTrue(r1.eligible_for_batch, f'{scope_name} should be eligible: {r1.warnings}')
                self.assertIn('echo "${PLUGIN_FOLDER}"', wf_path.read_text(encoding='utf-8'))
                r2 = gen.process_repository(repo_dir, apply=True, repo_name=repo_dir.name)
                self.assertEqual(0, r2.diff_bytes)

    def test_wire_contract_test_does_not_introduce_double_blank_line(self) -> None:
        tests_yml = """name: Tests
on: push
jobs:
  php84_compatibility:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Run PHP 8.4 scan
        run: php scripts/ci/php84-compat-scan.php "$PWD"

  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
"""
        wired = gen.wire_contract_test_in_tests_yml(tests_yml)
        self.assertNotIn('\n\n\n', wired, f'Double blank line found in wired tests.yml:\n{wired!r}')
        self.assertEqual(wired, gen.wire_contract_test_in_tests_yml(wired))

        # Also verify on real BeplyA3 fixture tests.yml
        a3_tests = (FIXTURES_DIR / 'BeplyA3' / '.github' / 'workflows' / 'tests.yml').read_text(encoding='utf-8')
        self.assertNotIn('\n\n\n', a3_tests)
        a3_wired = gen.wire_contract_test_in_tests_yml(gen.transform_workflow_text(a3_tests))
        self.assertNotIn('\n\n\n', a3_wired)

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
            any(
                'python3 -B -m unittest scripts/ci/test_workflow_no_steps_outputs_in_run.py'
                in str(s.get('run', ''))
                for s in php84_steps
            ),
            'Contract test must be wired into php84_compatibility with python3 -B',
        )
        self.assertIn('sys.dont_write_bytecode = True', gen.CONTRACT_TEST_SOURCE)
        # Idempotency check
        self.assertEqual(wired, gen.wire_contract_test_in_tests_yml(wired))


if __name__ == '__main__':
    unittest.main()
