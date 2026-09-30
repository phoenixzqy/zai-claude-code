"""Validate manual-only Actions and shared instruction/skill discovery."""

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]


class UniqueLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f'Duplicate YAML key: {key}')
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def check(root):
    workflows = sorted((root / '.github/workflows').glob('*.yml'))
    workflows += sorted((root / '.github/workflows').glob('*.yaml'))
    if not workflows:
        raise ValueError('No retained manual workflows found.')
    for path in workflows:
        workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)
        events = workflow.get('on') if isinstance(workflow, dict) else None
        if not isinstance(events, dict) or set(events) != {'workflow_dispatch'}:
            raise ValueError(f'{path.name}: only workflow_dispatch is allowed.')
    canonical = root / 'AGENTS.md'
    for name in ('CLAUDE.md', '.github/copilot-instructions.md'):
        path = root / name
        if (not path.is_symlink() or path.readlink().is_absolute()
                or path.resolve() != canonical.resolve()):
            raise ValueError(f'{name}: must link to AGENTS.md.')
    skills = root / '.agents/skills'
    for name in ('.claude/skills', '.codex/skills', '.github/skills'):
        path = root / name
        if (not path.is_symlink() or path.readlink().is_absolute()
                or path.resolve() != skills.resolve()):
            raise ValueError(f'{name}: must link to .agents/skills.')
    for path in skills.iterdir():
        if not (path / 'SKILL.md').is_file():
            raise ValueError(f'{path.name}: missing canonical SKILL.md.')
    print(f'OK: {len(workflows)} manual-only workflows and shared agent links.')


def main():
    try:
        check(ROOT)
        return 0
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f'Local CI policy failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
