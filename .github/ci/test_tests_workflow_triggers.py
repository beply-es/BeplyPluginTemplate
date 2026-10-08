"""One Tests run per SHA, and no heavy CI on draft PRs (P18).

push runs only on the release branch(es) and v* tags: the release gate waits
for the Tests run of exactly that ref and event, so those stay. Feature
branches get their single run from pull_request. Only PR runs share a group
and cancel each other; every push/dispatch run gets its own group (event,
ref, SHA), so a newer main or tag push never cancels, queues or serialises
the run a release waits for (GitHub cancels a *pending* run in a shared
group even with cancel-in-progress false). Draft PRs run the light job(s)
only; ready_for_review starts the rest.

Any other workflow that waits for this Tests run (a release gate) must not
fire where Tests no longer runs: if it runs on pushes outside the release
branches, its waiting job needs a job-level `if` limited to tags (and the
release branch), or it would hold a runner until it times out.
"""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "tests.yml"
RELEASE_BRANCHES = ["main"]
LIGHT_JOBS = {"quality_contract"}
DRAFT_GUARD = "github.event.pull_request.draft != true"
WAITS_FOR_TESTS = re.compile(
    r"""(?:\.get\(\s*["']name["']\s*\)|\[["']name["']\])\s*==\s*["']Tests["']|wait_for_tests\.py"""
)
TAG_PREDICATE = re.compile(r"refs/tags/|ref_type == 'tag'")


def job_blocks(text):
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\n", text.split("\njobs:\n", 1)[1], flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def job_if(block):
    match = re.search(r"^    if: *(.*)$", block, re.M)
    return match.group(1) if match else ""


def push_branches(text):
    head = text.split("\njobs:\n", 1)[0]
    push = re.search(r"^  push:(.*)\n((?:    .*\n|      .*\n)*)", head, re.M)
    if not push:
        return []
    body = push.group(2)
    inline = re.search(r"^    branches: *\[(.*)\]", body, re.M)
    if inline:
        return [item.strip().strip("'\"") for item in inline.group(1).split(",") if item.strip()]
    listed = re.search(r"^    branches:\n((?:      - .*\n)+)", body, re.M)
    if listed:
        return [line.strip()[2:].strip().strip("'\"") for line in listed.group(1).splitlines()]
    return [] if re.search(r"^    tags:", body, re.M) else ["**"]


def needs_of(block):
    match = re.search(r"^    needs: *(.*)\n((?:      - .*\n)*)", block, re.M)
    if not match:
        return []
    inline = match.group(1).strip()
    if inline.startswith("["):
        return [item.strip() for item in inline.strip("[]").split(",") if item.strip()]
    if inline:
        return [inline]
    return [line.strip()[2:].strip() for line in match.group(2).splitlines()]


class TestsWorkflowTriggersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.head = cls.text.split("\njobs:\n", 1)[0]
        cls.jobs = job_blocks(cls.text)

    def test_push_runs_only_on_release_branches_and_tags(self):
        branches = "".join(f"      - {branch}\n" for branch in RELEASE_BRANCHES)
        expected = (
            "\non:\n  push:\n    branches:\n" + branches + "    tags:\n      - 'v*'\n"
            "  pull_request:\n    types: [opened, synchronize, reopened, ready_for_review]\n"
            "  workflow_dispatch:\n"
        )
        self.assertIn(expected, self.head)
        self.assertEqual(self.head.count("\non:\n"), 1)
        self.assertNotIn("'**'", self.head)

    def test_only_pull_request_runs_cancel_each_other(self):
        self.assertRegex(
            self.head,
            r"\nconcurrency:\n  group: [^\n]*\$\{\{ github\.event_name == 'pull_request' && format\('pr-\{0\}', "
            r"github\.event\.pull_request\.number\) \|\| format\('\{0\}-\{1\}-\{2\}', github\.event_name, github\.ref, "
            r"github\.sha\) \}\}\n"
            r"  cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}\n",
        )

    def test_draft_pull_requests_run_only_the_light_jobs(self):
        self.assertTrue(LIGHT_JOBS and LIGHT_JOBS <= set(self.jobs), sorted(self.jobs))
        guarded = {}

        def is_guarded(job):
            if job not in guarded:
                block = self.jobs[job]
                needs = needs_of(block)
                # A job-level always()/failure() would start the job although its needs were skipped.
                condition = job_if(block)
                guarded[job] = DRAFT_GUARD in condition or (
                    bool(needs)
                    and not re.search(r"\b(always|failure|cancelled)\(\)", condition)
                    and all(is_guarded(need) for need in needs)
                )
            return guarded[job]

        for job in self.jobs:
            with self.subTest(job=job):
                if job in LIGHT_JOBS:
                    self.assertNotIn(DRAFT_GUARD, job_if(self.jobs[job]))
                    self.assertFalse(any(is_guarded(need) for need in needs_of(self.jobs[job])))
                else:
                    self.assertTrue(is_guarded(job), f"{job} would run on a draft PR")

    def test_release_gates_waiting_for_tests_only_run_where_tests_runs(self):
        for path in sorted(WORKFLOW.parent.glob("*.y*ml")):
            text = path.read_text(encoding="utf-8")
            if path == WORKFLOW or not WAITS_FOR_TESTS.search(text):
                continue
            if set(push_branches(text)) <= set(RELEASE_BRANCHES):
                continue
            for job, block in job_blocks(text).items():
                if WAITS_FOR_TESTS.search(block):
                    with self.subTest(workflow=path.name, job=job):
                        self.assertRegex(job_if(block), TAG_PREDICATE,
                                         f"{job} waits for Tests on every branch push")


if __name__ == "__main__":
    unittest.main()
