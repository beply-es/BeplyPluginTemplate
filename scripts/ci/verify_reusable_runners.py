"""Fail closed when a reusable workflow can select an unapproved runner."""
from pathlib import Path

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken

ARC_ONLY = "${{ vars.BEPLY_GHA_RUNNER == 'arc-runner-prio' && 'arc-runner-prio' || 'arc-runner-set' }}"


def calls_reusable(trigger):
    if isinstance(trigger, str):
        return trigger == 'workflow_call'
    return isinstance(trigger, (dict, list)) and 'workflow_call' in trigger


class UniqueBaseLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise yaml.YAMLError('duplicate or non-scalar mapping key')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def check_workflow(text):
    """Return violations; never execute workflow code or evaluate expressions."""
    try:
        if not isinstance(text, str):
            return ['workflow must be text']
        if any(isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in yaml.scan(text)):
            return ['YAML anchors, aliases and explicit tags are not accepted']
        document = yaml.load(text, Loader=UniqueBaseLoader)
        if not isinstance(document, dict):
            return ['workflow must be a mapping']
        trigger = document.get('on')
        if not calls_reusable(trigger):
            return ['workflow_call is required']
        jobs = document.get('jobs')
        if not isinstance(jobs, dict) or not jobs:
            return ['nonempty jobs mapping is required']
        errors = []
        for name, job in jobs.items():
            if not isinstance(job, dict):
                errors.append(f'{name}: job must be a mapping')
            elif 'uses' in job:
                errors.append(f'{name}: nested reusable workflow requires separate review')
            elif job.get('runs-on') != ARC_ONLY:
                errors.append(f'{name}: runner selector is not the closed ARC expression')
        return errors
    except (yaml.YAMLError, RecursionError, TypeError, ValueError):
        return ['invalid or unsupported YAML']


def check_repository(workflows, required=()):
    """Discover workflow_call in every workflow, independently of its filename."""
    if not isinstance(workflows, dict) or not workflows:
        return ['no workflows supplied']
    errors = []
    discovered = set()
    for name, text in sorted(workflows.items()):
        try:
            document = yaml.load(text, Loader=UniqueBaseLoader)
            if not isinstance(document, dict):
                raise ValueError('workflow must be a mapping')
            trigger = document.get('on')
            if not isinstance(trigger, (dict, list, str)) or not trigger:
                raise ValueError('workflow must declare triggers')
            if calls_reusable(trigger):
                discovered.add(name)
                errors.extend(f'{name}: {error}' for error in check_workflow(text))
        except (yaml.YAMLError, RecursionError, TypeError, ValueError):
            errors.append(f'{name}: invalid or unsupported YAML')
    errors.extend(f'{name}: required reusable workflow missing' for name in sorted(set(required) - discovered))
    return errors


def main():
    root = Path(__file__).resolve().parents[2]
    directory = root / '.github/workflows'
    paths = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in {'.yml', '.yaml'})
    documents = {path.name: path.read_text(encoding='utf-8') for path in paths}
    is_template = 'name = BeplyPluginTemplate' in (root / 'facturascripts.ini').read_text(encoding='utf-8')
    required = ('reusable-immutable-plugin-candidate.yml', 'reusable-promote-immutable-plugin-candidate.yml') if is_template else ()
    errors = check_repository(documents, required=required)
    if errors:
        raise SystemExit('; '.join(errors))
    print('Reusable workflow runner selectors are closed')


if __name__ == '__main__':
    main()
