#!/usr/bin/env python3
"""Idempotent generator: move ${{ steps.*.outputs.* }} out of workflow run: blocks into env:.

Design goals:
- Surgical, line-preserving edits using PyYAML's compose marks (untouched YAML stays byte-identical).
- Respects original shell quoting context (C1/C2):
  - Unquoted: ${VAR} (preserves word-splitting for *targets lists; shell never executes $(...)).
  - Inside double quotes ("..."): ${VAR} (keeps surrounding double quotes).
  - Inside single quotes ('...'): closes & reopens single quotes as '"${VAR}"' (or "${VAR}" if bare).
- Fail-closed on unsupported patterns (C3): never rewrites compound expressions
  (${{ steps.a.outputs.x || ... }}) or with.script (github-script / ssh-action); reports them
  explicitly in warnings and marks eligible_for_batch=False.
- Injects scripts/ci/test_workflow_no_steps_outputs_in_run.py (checking both run: and with.script)
  and wires it in tests.yml if needed.
- Computes a normalized diff SHA-256 (replacing repo-specific names with <REPO>) for batch auditing.
- Supports --dry-run (default) and --apply; guaranteed idempotent (2nd pass diff = 0 bytes).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class InvalidWorkflowYamlError(RuntimeError):
    """Raised when a workflow YAML file cannot be parsed cleanly."""

    def __init__(self, workflow_path: str, detail: str) -> None:
        self.workflow_path = workflow_path
        self.detail = detail
        super().__init__(f'Invalid YAML in {workflow_path}: {detail}')


STEPS_OUTPUT_EXPR_RE = re.compile(
    r'\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)\s*\}\}'
)
ANY_STEPS_OUTPUT_EXPR_RE = re.compile(
    r'\$\{\{[^}]*steps\.[A-Za-z0-9_-]+\.outputs\.[A-Za-z0-9_-]+[^}]*\}\}'
)

CANONICAL_ENV_NAMES: dict[tuple[str, str], str] = {
    ('ini', 'name'): 'PLUGIN_NAME',
    ('ini', 'version'): 'PLUGIN_VERSION',
    ('ini', 'min_version'): 'PLUGIN_MIN_VERSION',
    ('ini', 'max_version'): 'PLUGIN_MAX_VERSION',
    ('ini', 'min_php'): 'PLUGIN_MIN_PHP',
    ('ini', 'description'): 'PLUGIN_DESCRIPTION',
    ('unit-targets', 'config'): 'PHPUNIT_CONFIG',
    ('unit-targets', 'targets'): 'PHPUNIT_TARGETS',
    ('runtime-targets', 'config'): 'PHPUNIT_CONFIG',
    ('runtime-targets', 'coverage_config'): 'PHPUNIT_COVERAGE_CONFIG',
    ('runtime-targets', 'targets'): 'PHPUNIT_TARGETS',
    ('integration-targets', 'targets'): 'PHPUNIT_TARGETS',
    ('e2e-targets', 'targets'): 'E2E_TARGETS',
    ('e2e-targets', 'tests_dir'): 'E2E_TESTS_DIR',
    ('test-targets', 'phpunit_targets_file'): 'PHPUNIT_TARGETS_FILE',
    ('test-targets', 'script_targets_file'): 'SCRIPT_TARGETS_FILE',
    ('build_zip', 'zip_path'): 'PLUGIN_ZIP',
    ('build_zip', 'published_at'): 'SOURCE_PUBLISHED_AT',
    ('download', 'zip'): 'PLUGIN_ZIP',
    ('download', 'release_url'): 'SOURCE_RELEASE_URL',
    ('download', 'published_at'): 'SOURCE_PUBLISHED_AT',
    ('dev_provenance', 'published_at'): 'SOURCE_PUBLISHED_AT',
    ('prod_provenance', 'published_at'): 'SOURCE_PUBLISHED_AT',
    ('release_metadata', 'published_at'): 'SOURCE_PUBLISHED_AT',
    ('dev_release_metadata', 'source_branch'): 'SOURCE_BRANCH',
    ('dev_release_metadata', 'source_release_tag'): 'SOURCE_RELEASE_TAG',
    ('dev_release_metadata', 'source_release_url'): 'SOURCE_RELEASE_URL',
    ('published_release', 'tag'): 'SOURCE_RELEASE_TAG',
    ('published_release', 'url'): 'SOURCE_RELEASE_URL',
    ('published_release', 'release_url'): 'SOURCE_RELEASE_URL',
    ('published_release', 'published_at'): 'SOURCE_PUBLISHED_AT',
    ('meta', 'prod_tag'): 'PROD_TAG',
    ('contract', 'sha'): 'CONTRACT_SHA',
}

CONTRACT_TEST_REL_PATH = Path('scripts/ci/test_workflow_no_steps_outputs_in_run.py')

CONTRACT_TEST_SOURCE = '''#!/usr/bin/env python3
"""Contract test: reject ${{ steps.*.outputs.* }} interpolation inside run: and with.script blocks."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - fallback for runners without PyYAML
    yaml = None


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / '.github' / 'workflows'
STEPS_OUTPUTS_RE = re.compile(r'\\$\\{\\{[^}]*steps\\.[^}]+\\.outputs\\.[^}]+\\}\\}')


def _find_with_pyyaml(workflow_text: str, workflow_name: str) -> list[str]:
    data = yaml.safe_load(workflow_text)
    if not isinstance(data, dict):
        return []

    violations: list[str] = []
    jobs = data.get('jobs') or {}
    if not isinstance(jobs, dict):
        return []

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get('steps') or []
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_label = step.get('name') or f'step[{idx}]'
            run_script = step.get('run')
            if isinstance(run_script, str):
                matches = STEPS_OUTPUTS_RE.findall(run_script)
                if matches:
                    violations.append(
                        f'{workflow_name} :: job {job_id} :: {step_label!r} (run) -> {sorted(set(matches))}'
                    )
            with_cfg = step.get('with')
            if isinstance(with_cfg, dict):
                script_val = with_cfg.get('script')
                if isinstance(script_val, str):
                    matches = STEPS_OUTPUTS_RE.findall(script_val)
                    if matches:
                        violations.append(
                            f'{workflow_name} :: job {job_id} :: {step_label!r} (with.script) -> {sorted(set(matches))}'
                        )
    return violations


def _find_fallback(workflow_text: str, workflow_name: str) -> list[str]:
    violations: list[str] = []
    lines = workflow_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^(\\s*(?:-\\s+)?)(run|script)\\s*:(.*)$', line)
        if not m:
            i += 1
            continue
        key_indent = len(m.group(1))
        key_name = m.group(2)
        rest = m.group(3).strip()
        if rest and not re.match(r'^[|>][0-9+-]*$', rest):
            matches = STEPS_OUTPUTS_RE.findall(rest)
            if matches:
                violations.append(
                    f'{workflow_name} :: line {i + 1} ({key_name}) -> {sorted(set(matches))}'
                )
            i += 1
            continue
        block_lines: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.strip() == '':
                block_lines.append(nxt)
                j += 1
                continue
            nxt_indent = len(nxt) - len(nxt.lstrip(' '))
            if nxt_indent <= key_indent:
                break
            block_lines.append(nxt)
            j += 1
        matches = STEPS_OUTPUTS_RE.findall('\\n'.join(block_lines))
        if matches:
            violations.append(
                f'{workflow_name} :: line {i + 1} ({key_name}) -> {sorted(set(matches))}'
            )
        i = j
    return violations


def find_steps_outputs_in_run(workflow_text: str, workflow_name: str = '<memory>') -> list[str]:
    """Return violations where ${{ steps.*.outputs.* }} is interpolated inside run: or with.script."""
    if yaml is not None:
        return _find_with_pyyaml(workflow_text, workflow_name)
    return _find_fallback(workflow_text, workflow_name)


class WorkflowNoStepsOutputsInRunTest(unittest.TestCase):
    def test_detects_unsafe_interpolation_in_run_block(self) -> None:
        unsafe_workflow = """
name: Unsafe
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Bad step
        run: echo "v${{ steps.ini.outputs.version }}"
"""
        violations = find_steps_outputs_in_run(unsafe_workflow, 'unsafe.yml')
        self.assertEqual(1, len(violations))
        self.assertIn('steps.ini.outputs.version', violations[0])

    def test_detects_unsafe_interpolation_in_with_script(self) -> None:
        unsafe_script_workflow = """
name: Unsafe Script
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
        violations = find_steps_outputs_in_run(unsafe_script_workflow, 'unsafe-script.yml')
        self.assertEqual(1, len(violations))
        self.assertIn('with.script', violations[0])
        self.assertIn('steps.ini.outputs.name', violations[0])

    def test_allows_steps_outputs_passed_via_env(self) -> None:
        safe_workflow = """
name: Safe
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Safe step
        env:
          PLUGIN_VERSION: ${{ steps.ini.outputs.version }}
        run: echo "v${PLUGIN_VERSION}"
"""
        self.assertEqual([], find_steps_outputs_in_run(safe_workflow, 'safe.yml'))

    def test_all_repository_workflows_forbid_steps_outputs_in_run(self) -> None:
        workflow_files = sorted(
            list(WORKFLOWS_DIR.glob('*.yml')) + list(WORKFLOWS_DIR.glob('*.yaml'))
        )
        self.assertTrue(workflow_files, f'No workflow files found in {WORKFLOWS_DIR}')

        all_violations: list[str] = []
        for wf_path in workflow_files:
            all_violations.extend(
                find_steps_outputs_in_run(wf_path.read_text(encoding='utf-8'), wf_path.name)
            )

        self.assertEqual(
            [],
            all_violations,
            'Workflows must pass ${{ steps.*.outputs.* }} via env: instead of interpolating in run:/with.script:\\n'
            + '\\n'.join(all_violations),
        )


if __name__ == '__main__':
    unittest.main()
'''


def _canonical_env_name(step_id: str, output_name: str) -> str:
    if (step_id, output_name) in CANONICAL_ENV_NAMES:
        return CANONICAL_ENV_NAMES[(step_id, output_name)]
    clean_step = re.sub(r'[^A-Za-z0-9]+', '_', step_id).strip('_').upper()
    clean_out = re.sub(r'[^A-Za-z0-9]+', '_', output_name).strip('_').upper()
    if clean_step.endswith('ATTESTATION') or clean_out.startswith(('ARTIFACT_', 'SBOM_', 'HAS_ATTESTATION')):
        return f'{clean_step}_{clean_out}'
    return f'STEP_{clean_step}_{clean_out}'


def _quote_context(line: str, match_start: int) -> str:
    """Return shell quote context at match_start: 'single', 'double', or 'none'."""
    in_single = False
    in_double = False
    escaped = False
    for ch in line[:match_start]:
        if escaped:
            escaped = False
            continue
        if ch == '\\' and not in_single:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
    if in_single:
        return 'single'
    if in_double:
        return 'double'
    return 'none'


def _is_directly_single_quoted(line: str, start: int, end: int) -> bool:
    return start > 0 and end < len(line) and line[start - 1] == "'" and line[end] == "'"


def _replace_in_run_line(line: str, mapping: dict[tuple[str, str], str]) -> str:
    """Replace all simple ${{ steps.X.outputs.Y }} in a run: line respecting original quotes.

    - Unquoted -> ${VAR} (preserves word-splitting for *targets lists; shell never executes $(...)).
    - Inside double quotes -> ${VAR} (keeps surrounding double quotes).
    - Directly single-quoted ('${{ ... }}') -> "${VAR}".
    - Embedded inside single quotes ('prefix-${{ ... }}-suffix') -> 'prefix-'"${VAR}"'-suffix'.
    """
    out_parts: list[str] = []
    pos = 0
    for m in STEPS_OUTPUT_EXPR_RE.finditer(line):
        key = (m.group(1), m.group(2))
        var_name = mapping[key]
        start, end = m.span()
        ctx = _quote_context(line, start)
        if ctx == 'single':
            if _is_directly_single_quoted(line, start, end):
                out_parts.append(line[pos : start - 1])
                out_parts.append(f'"${{{var_name}}}"')
                pos = end + 1
            else:
                out_parts.append(line[pos:start])
                out_parts.append(f'\'"${{{var_name}}}"\'')
                pos = end
        else:
            # Both 'double' and 'none' substitute ${VAR} without adding extra double quotes.
            out_parts.append(line[pos:start])
            out_parts.append(f'${{{var_name}}}')
            pos = end
    out_parts.append(line[pos:])
    return ''.join(out_parts)


def _node_line_span(node: yaml.Node) -> tuple[int, int]:
    """Return 0-based [start_line, end_line_exclusive) for a PyYAML node.

    PyYAML sets end_mark on block mappings/sequences to the first token of the
    *following* sibling (so column > 0 on the next sibling's line). Only
    single-line/inline scalars ending mid-line need +1.
    """
    start = node.start_mark.line
    end = node.end_mark.line
    if isinstance(node, yaml.ScalarNode):
        if node.end_mark.column > 0 or end == start:
            end += 1
    else:
        if end == start:
            end += 1
    return start, end


def _get_mapping_pair(
    mapping_node: yaml.MappingNode, target_key: str
) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    for k_node, v_node in mapping_node.value:
        if isinstance(k_node, yaml.ScalarNode) and k_node.value == target_key:
            return k_node, v_node
    return None


def _normalize_expr(expr: str) -> tuple[str, str] | None:
    m = STEPS_OUTPUT_EXPR_RE.fullmatch(expr.strip())
    if not m:
        return None
    return (m.group(1), m.group(2))


def analyze_and_transform_workflow_text(
    text: str, workflow_name: str = '<memory>'
) -> tuple[str, list[dict[str, Any]]]:
    """Move supported ${{ steps.*.outputs.* }} from run: into env:; report unsupported ones.

    Returns (transformed_text, warnings). Steps with compound expressions or with.script
    interpolations are never rewritten and are recorded in warnings so callers fail closed.
    """
    warnings: list[dict[str, Any]] = []
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise InvalidWorkflowYamlError(workflow_name, str(exc).splitlines()[0]) from exc
    if not isinstance(root, yaml.MappingNode):
        return text, warnings

    jobs_pair = _get_mapping_pair(root, 'jobs')
    if not jobs_pair or not isinstance(jobs_pair[1], yaml.MappingNode):
        return text, warnings

    lines = text.splitlines(keepends=True)
    insertions: list[tuple[int, list[str]]] = []

    for job_k, job_node in jobs_pair[1].value:
        job_id = job_k.value if isinstance(job_k, yaml.ScalarNode) else '<job>'
        if not isinstance(job_node, yaml.MappingNode):
            continue
        steps_pair = _get_mapping_pair(job_node, 'steps')
        if not steps_pair or not isinstance(steps_pair[1], yaml.SequenceNode):
            continue

        for step_idx, step_node in enumerate(steps_pair[1].value):
            if not isinstance(step_node, yaml.MappingNode):
                continue
            name_pair = _get_mapping_pair(step_node, 'name')
            step_label = (
                name_pair[1].value
                if name_pair and isinstance(name_pair[1], yaml.ScalarNode)
                else f'step[{step_idx}]'
            )

            # C3: Fail-closed on with.script (github-script, ssh-action, etc.)
            with_pair = _get_mapping_pair(step_node, 'with')
            if with_pair and isinstance(with_pair[1], yaml.MappingNode):
                script_pair = _get_mapping_pair(with_pair[1], 'script')
                if script_pair and isinstance(script_pair[1], yaml.ScalarNode):
                    script_matches = ANY_STEPS_OUTPUT_EXPR_RE.findall(script_pair[1].value)
                    if script_matches:
                        warnings.append(
                            {
                                'kind': 'unsupported_with_script',
                                'workflow': workflow_name,
                                'job': job_id,
                                'step': step_label,
                                'expressions': sorted(set(script_matches)),
                            }
                        )

            run_pair = _get_mapping_pair(step_node, 'run')
            if not run_pair:
                continue
            run_k, run_v = run_pair
            if not isinstance(run_v, yaml.ScalarNode):
                continue

            # C3: Fail-closed on compound expressions inside run:
            all_any_matches = ANY_STEPS_OUTPUT_EXPR_RE.findall(run_v.value)
            unsupported_exprs = [
                expr for expr in all_any_matches if not STEPS_OUTPUT_EXPR_RE.fullmatch(expr)
            ]
            if unsupported_exprs:
                warnings.append(
                    {
                        'kind': 'unsupported_compound_expression',
                        'workflow': workflow_name,
                        'job': job_id,
                        'step': step_label,
                        'expressions': sorted(set(unsupported_exprs)),
                    }
                )
                continue

            pairs_in_order: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for m in STEPS_OUTPUT_EXPR_RE.finditer(run_v.value):
                pair = (m.group(1), m.group(2))
                if pair not in seen:
                    seen.add(pair)
                    pairs_in_order.append(pair)
            if not pairs_in_order:
                continue

            # Inspect existing env: mapping on this step
            env_pair = _get_mapping_pair(step_node, 'env')
            existing_by_expr: dict[tuple[str, str], str] = {}
            used_env_names: set[str] = set()
            if env_pair and isinstance(env_pair[1], yaml.MappingNode):
                for ek, ev in env_pair[1].value:
                    if isinstance(ek, yaml.ScalarNode):
                        used_env_names.add(ek.value)
                        if isinstance(ev, yaml.ScalarNode):
                            norm = _normalize_expr(ev.value)
                            if norm is not None:
                                existing_by_expr[norm] = ek.value

            expr_to_var: dict[tuple[str, str], str] = {}
            new_env_entries: list[tuple[str, str]] = []
            for pair in pairs_in_order:
                if pair in existing_by_expr:
                    expr_to_var[pair] = existing_by_expr[pair]
                    continue
                base_name = _canonical_env_name(pair[0], pair[1])
                candidate = base_name
                suffix = 2
                while candidate in used_env_names:
                    candidate = f'{base_name}_{suffix}'
                    suffix += 1
                used_env_names.add(candidate)
                expr_to_var[pair] = candidate
                new_env_entries.append((candidate, f'${{{{ steps.{pair[0]}.outputs.{pair[1]} }}}}'))

            # Rewrite ONLY the lines belonging to run_v
            run_start, run_end = _node_line_span(run_v)
            for idx in range(run_start, min(run_end, len(lines))):
                raw = lines[idx]
                if not STEPS_OUTPUT_EXPR_RE.search(raw):
                    continue
                newline = '\n' if raw.endswith('\n') else ''
                body = raw[:-1] if newline else raw
                if idx == run_k.start_mark.line:
                    colon_pos = body.find(':', run_k.start_mark.column)
                    prefix = body[: colon_pos + 1]
                    rhs = body[colon_pos + 1 :]
                    lines[idx] = prefix + _replace_in_run_line(rhs, expr_to_var) + newline
                else:
                    lines[idx] = _replace_in_run_line(body, expr_to_var) + newline

            # Schedule env: insertion if new variables were added
            if new_env_entries:
                if env_pair and isinstance(env_pair[1], yaml.MappingNode) and env_pair[1].value:
                    last_k, last_v = env_pair[1].value[-1]
                    entry_indent = ' ' * last_k.start_mark.column
                    _, insert_line = _node_line_span(last_v)
                    add_lines = [f'{entry_indent}{k}: {v}\n' for k, v in new_env_entries]
                    insertions.append((insert_line, add_lines))
                else:
                    key_col = run_k.start_mark.column
                    run_line_idx = run_k.start_mark.line
                    run_line_text = lines[run_line_idx]
                    dash_prefix_match = re.match(r'^(\s*-\s+)run\s*:', run_line_text)
                    if dash_prefix_match:
                        dash_prefix = dash_prefix_match.group(1)
                        key_indent = ' ' * key_col
                        entry_indent = ' ' * (key_col + 2)
                        lines[run_line_idx] = key_indent + run_line_text[len(dash_prefix) :]
                        add_lines = [f'{dash_prefix}env:\n'] + [
                            f'{entry_indent}{k}: {v}\n' for k, v in new_env_entries
                        ]
                        insertions.append((run_line_idx, add_lines))
                    else:
                        key_indent = ' ' * key_col
                        entry_indent = ' ' * (key_col + 2)
                        add_lines = [f'{key_indent}env:\n'] + [
                            f'{entry_indent}{k}: {v}\n' for k, v in new_env_entries
                        ]
                        insertions.append((run_line_idx, add_lines))

    for insert_line, add_lines in sorted(insertions, key=lambda item: item[0], reverse=True):
        lines[insert_line:insert_line] = add_lines

    result = ''.join(lines)
    yaml.safe_load(result)
    return result, warnings


def transform_workflow_text(text: str) -> str:
    """Convenience wrapper returning only the transformed YAML text."""
    transformed, _ = analyze_and_transform_workflow_text(text)
    return transformed


def wire_contract_test_in_tests_yml(text: str) -> str:
    """Ensure tests.yml runs scripts/ci/test_workflow_no_steps_outputs_in_run.py (idempotent)."""
    if 'test_workflow_no_steps_outputs_in_run.py' in text:
        return text
    if re.search(r"unittest\s+discover\s+-s\s+scripts/ci\s+-p\s+['\"]test_\*\.py['\"]", text):
        return text

    root = yaml.compose(text)
    if not isinstance(root, yaml.MappingNode):
        return text
    jobs_pair = _get_mapping_pair(root, 'jobs')
    if not jobs_pair or not isinstance(jobs_pair[1], yaml.MappingNode):
        return text

    preferred_jobs = (
        'quality_contract',
        'release_contract',
        'php84_compat',
        'php_compat',
        'php82_compat',
        'lint',
    )
    job_nodes = {
        k.value: v
        for k, v in jobs_pair[1].value
        if isinstance(k, yaml.ScalarNode) and isinstance(v, yaml.MappingNode)
    }
    target_job = None
    for candidate in preferred_jobs:
        if candidate in job_nodes:
            target_job = job_nodes[candidate]
            break
    if target_job is None and job_nodes:
        target_job = next(iter(job_nodes.values()))
    if target_job is None:
        return text

    steps_pair = _get_mapping_pair(target_job, 'steps')
    if not steps_pair or not isinstance(steps_pair[1], yaml.SequenceNode) or not steps_pair[1].value:
        return text

    first_step = steps_pair[1].value[0]
    last_step = steps_pair[1].value[-1]
    step_indent = ' ' * max(0, first_step.start_mark.column - 2)
    lines = text.splitlines(keepends=True)
    first_step_line = lines[first_step.start_mark.line]
    m_dash = re.match(r'^(\s*)-\s', first_step_line)
    if m_dash:
        step_indent = m_dash.group(1)
    prop_indent = step_indent + '  '

    _, insert_line = _node_line_span(last_step)
    new_step = [
        '\n',
        f'{step_indent}- name: Test workflow steps.outputs env contract\n',
        f'{prop_indent}run: python3 -B -m unittest scripts/ci/test_workflow_no_steps_outputs_in_run.py\n',
    ]
    lines[insert_line:insert_line] = new_step
    result = ''.join(lines)
    yaml.safe_load(result)
    return result


def _detect_repo_name(repo_root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    ini_path = repo_root / 'facturascripts.ini'
    if ini_path.is_file():
        for line in ini_path.read_text(encoding='utf-8', errors='replace').splitlines():
            m = re.match(r'^\s*name\s*=\s*["\']?([^"\'\r\n]+)["\']?\s*$', line)
            if m:
                return m.group(1).strip()
    return repo_root.name


def compute_normalized_diff(
    changes: dict[str, tuple[str, str]], repo_name: str
) -> tuple[str, str]:
    """Return (normalized_unified_diff, sha256_hex) across all changed files."""
    diff_chunks: list[str] = []
    for rel_path in sorted(changes):
        before, after = changes[rel_path]
        if before == after:
            continue
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f'a/{rel_path}',
                tofile=f'b/{rel_path}',
                n=3,
            )
        )
        diff_chunks.extend(diff_lines)

    raw_diff = ''.join(diff_chunks)
    normalized = raw_diff
    if repo_name:
        normalized = re.sub(re.escape(repo_name), '<REPO>', normalized)
        normalized = re.sub(re.escape(repo_name.lower()), '<repo>', normalized)
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return normalized, digest


@dataclass
class GeneratorResult:
    repo_root: str
    repo_name: str
    applied: bool
    changed_files: list[str] = field(default_factory=list)
    normalized_diff_sha256: str = ''
    diff_bytes: int = 0
    normalized_diff: str = ''
    warnings: list[dict[str, Any]] = field(default_factory=list)
    eligible_for_batch: bool = True


def process_repository(
    repo_root: Path,
    *,
    apply: bool = False,
    inject_test: bool = True,
    repo_name: str | None = None,
) -> GeneratorResult:
    """Plan or apply workflow hardening to a plugin repository.

    Fail-closed (C3): if any workflow contains unsupported patterns (compound expressions
    or with.script interpolations), they are reported in warnings, eligible_for_batch is set
    to False, and no files are modified when apply=True.
    """
    repo_root = repo_root.resolve()
    resolved_name = _detect_repo_name(repo_root, repo_name)
    workflows_dir = repo_root / '.github' / 'workflows'
    changes: dict[str, tuple[str, str]] = {}
    warnings: list[dict[str, Any]] = []

    if workflows_dir.is_dir():
        wf_files = sorted(
            list(workflows_dir.glob('*.yml')) + list(workflows_dir.glob('*.yaml'))
        )
        for wf_path in wf_files:
            rel = wf_path.relative_to(repo_root).as_posix()
            before = wf_path.read_text(encoding='utf-8')
            after, wf_warnings = analyze_and_transform_workflow_text(before, workflow_name=rel)
            warnings.extend(wf_warnings)
            if inject_test and wf_path.name == 'tests.yml':
                after = wire_contract_test_in_tests_yml(after)
            if after != before:
                changes[rel] = (before, after)

    eligible_for_batch = len(warnings) == 0
    if not eligible_for_batch:
        # Fail closed: leave the repository untouched and out of the automated batch.
        return GeneratorResult(
            repo_root=str(repo_root),
            repo_name=resolved_name,
            applied=False,
            changed_files=[],
            normalized_diff_sha256='',
            diff_bytes=0,
            normalized_diff='',
            warnings=warnings,
            eligible_for_batch=False,
        )

    if inject_test:
        test_path = repo_root / CONTRACT_TEST_REL_PATH
        rel = CONTRACT_TEST_REL_PATH.as_posix()
        before = test_path.read_text(encoding='utf-8') if test_path.is_file() else ''
        after = CONTRACT_TEST_SOURCE
        if after != before:
            changes[rel] = (before, after)

    normalized_diff, digest = compute_normalized_diff(changes, resolved_name)

    if apply:
        for rel, (_, after) in sorted(changes.items()):
            dest = repo_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(after, encoding='utf-8')

    return GeneratorResult(
        repo_root=str(repo_root),
        repo_name=resolved_name,
        applied=apply,
        changed_files=sorted(changes.keys()),
        normalized_diff_sha256=digest,
        diff_bytes=len(normalized_diff.encode('utf-8')),
        normalized_diff=normalized_diff,
        warnings=[],
        eligible_for_batch=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Move ${{ steps.*.outputs.* }} out of workflow run: blocks into env:.'
    )
    parser.add_argument('--repo', required=True, type=Path, help='Path to target plugin repository')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', default=True, help='Preview changes (default)')
    mode.add_argument('--apply', action='store_true', default=False, help='Write changes to disk')
    parser.add_argument('--repo-name', default=None, help='Override repo name for diff normalization')
    parser.add_argument(
        '--no-inject-test',
        action='store_true',
        default=False,
        help='Do not inject scripts/ci/test_workflow_no_steps_outputs_in_run.py',
    )
    parser.add_argument('--json', action='store_true', default=False, help='Emit JSON summary')
    args = parser.parse_args(argv)

    try:
        result = process_repository(
            args.repo,
            apply=args.apply,
            inject_test=not args.no_inject_test,
            repo_name=args.repo_name,
        )
    except InvalidWorkflowYamlError as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        return 2

    if args.json:
        payload: dict[str, Any] = {
            'repo_root': result.repo_root,
            'repo_name': result.repo_name,
            'applied': result.applied,
            'eligible_for_batch': result.eligible_for_batch,
            'changed_files': result.changed_files,
            'normalized_diff_sha256': result.normalized_diff_sha256,
            'diff_bytes': result.diff_bytes,
            'warnings': result.warnings,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mode_label = 'SKIPPED' if not result.eligible_for_batch else ('APPLIED' if result.applied else 'DRY-RUN')
        print(
            f'[{mode_label}] repo={result.repo_name} eligible={result.eligible_for_batch} '
            f'files={len(result.changed_files)} diff_bytes={result.diff_bytes} '
            f'normalized_diff_sha256={result.normalized_diff_sha256}'
        )
        for f in result.changed_files:
            print(f'  - {f}')
        for w in result.warnings:
            print(
                f"  ! WARN [{w['kind']}] {w['workflow']} :: {w['job']} :: {w['step']} -> {w['expressions']}"
            )

    return 0 if result.eligible_for_batch else 2


if __name__ == '__main__':
    raise SystemExit(main())
