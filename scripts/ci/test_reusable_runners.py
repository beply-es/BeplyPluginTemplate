"""Security contract for every reusable workflow's effective runner selector."""
import unittest
from pathlib import Path

from scripts.ci.verify_reusable_runners import check_repository, check_workflow

ROOT = Path(__file__).resolve().parents[2]
CLOSED = "${{ vars.BEPLY_GHA_RUNNER == 'arc-runner-prio' && 'arc-runner-prio' || 'arc-runner-set' }}"


def workflow(job):
    return "name: fixture\non:\n  workflow_call:\njobs:\n" + job


class ReusableRunnerContractTests(unittest.TestCase):
    def test_all_real_reusables_are_closed(self):
        workflows = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / '.github/workflows').iterdir()
                     if p.is_file() and p.suffix in {'.yml', '.yaml'}}
        is_template = 'name = BeplyPluginTemplate' in (ROOT / 'facturascripts.ini').read_text(encoding='utf-8')
        required = ('reusable-immutable-plugin-candidate.yml', 'reusable-promote-immutable-plugin-candidate.yml') if is_template else ()
        self.assertEqual([], check_repository(workflows, required=required))

    def test_discovers_reusables_with_any_name_or_yaml_extension(self):
        docs = {
            'ordinary.yml': 'on: push\njobs:\n  lint:\n    runs-on: ubuntu-latest\n',
            'hidden.yaml': workflow('  publish:\n    runs-on: ubuntu-latest\n    steps: []\n'),
        }
        self.assertTrue(check_repository(docs))
        docs['hidden.yaml'] = workflow(f'  publish:\n    runs-on: {CLOSED}\n    steps: []\n')
        self.assertEqual([], check_repository(docs))

    def test_missing_template_reusable_fails_but_callers_need_not_copy_one(self):
        docs = {'tests.yml': 'on: push\njobs:\n  lint:\n    runs-on: ubuntu-latest\n'}
        self.assertEqual([], check_repository(docs))
        self.assertTrue(check_repository(docs, required=('reusable-immutable-plugin-candidate.yml',)))

    def test_shorthand_workflow_call_cannot_hide_an_unsafe_job(self):
        docs = {'other.yml': 'on: [push, workflow_call]\njobs:\n  publish:\n    runs-on: ubuntu-latest\n'}
        self.assertTrue(check_repository(docs))
        docs['other.yml'] = docs['other.yml'].replace('ubuntu-latest', CLOSED)
        self.assertEqual([], check_repository(docs))

    def test_closed_selector_is_accepted(self):
        self.assertEqual([], check_workflow(workflow(f"  publish:\n    runs-on: {CLOSED}\n    steps: []\n")))

    def test_unsafe_hosted_and_variable_selectors_fail(self):
        for selector in ['ubuntu-latest', "${{ vars.BEPLY_GHA_RUNNER || 'arc-runner-set' }}", "${{ vars.BEPLY_GHA_RUNNER }}"]:
            with self.subTest(selector=selector):
                self.assertTrue(check_workflow(workflow(f"  publish:\n    runs-on: {selector}\n    steps: []\n")))

    def test_quoted_and_flow_keys_are_checked(self):
        for job in ["  publish:\n    'runs-on': ubuntu-latest\n    steps: []\n", "  publish: {runs-on: ubuntu-latest, steps: []}\n"]:
            with self.subTest(job=job):
                self.assertTrue(check_workflow(workflow(job)))

    def test_hidden_nested_reusable_and_missing_selector_fail(self):
        for job in ["  publish:\n    uses: example/repo/.github/workflows/release.yml@main\n", "  publish:\n    steps: []\n"]:
            with self.subTest(job=job):
                self.assertTrue(check_workflow(workflow(job)))

    def test_duplicate_job_key_and_yaml_alias_fail(self):
        samples = [
            workflow(f"  publish:\n    runs-on: {CLOSED}\n    runs-on: ubuntu-latest\n    steps: []\n"),
            workflow(f"  publish:\n    runs-on: &r {CLOSED}\n    steps: []\n  other:\n    runs-on: *r\n    steps: []\n"),
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(check_workflow(text))

    def test_invalid_and_empty_jobs_fail(self):
        for text in ['jobs: {}\n', 'jobs: [broken\n', 'name: missing jobs\n']:
            with self.subTest(text=text):
                self.assertTrue(check_workflow(text))


if __name__ == '__main__':
    unittest.main()
