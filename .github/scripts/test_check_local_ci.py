from pathlib import Path
import tempfile
import unittest

import check_local_ci


class PolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='local-ci-policy-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('.github/workflows', '.agents/skills/repo-sync', '.claude', '.codex'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'AGENTS.md').write_text('instructions', encoding='utf-8')
        (self.root / '.agents/skills/repo-sync/SKILL.md').write_text('skill', encoding='utf-8')
        (self.root / 'CLAUDE.md').symlink_to('AGENTS.md')
        (self.root / '.github/copilot-instructions.md').symlink_to('../AGENTS.md')
        for name in ('.claude', '.codex', '.github'):
            (self.root / name / 'skills').symlink_to('../.agents/skills', target_is_directory=True)
        self.workflow = self.root / '.github/workflows/test.yml'
        self.workflow.write_text('on:\n  workflow_dispatch:\n', encoding='utf-8')

    def test_manual_only_with_dispatch_inputs_is_valid(self):
        self.workflow.write_text(
            'on:\n  workflow_dispatch:\n    inputs:\n      ref:\n        type: string\n',
            encoding='utf-8',
        )
        check_local_ci.check(self.root)

    def test_every_automatic_event_is_rejected(self):
        for event in ('push', 'pull_request', 'issues', 'issue_comment', 'schedule',
                      'repository_dispatch', 'workflow_run', 'pull_request_target'):
            with self.subTest(event=event):
                self.workflow.write_text(f'on:\n  workflow_dispatch:\n  {event}:\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'only workflow_dispatch'):
                    check_local_ci.check(self.root)

    def test_duplicate_trigger_keys_are_not_silently_ignored(self):
        self.workflow.write_text('on:\n  push:\non:\n  workflow_dispatch:\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate YAML key'):
            check_local_ci.check(self.root)

    def test_new_upstream_yaml_workflow_is_checked(self):
        (self.workflow.parent / 'upstream.yaml').write_text('on: push\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'upstream.yaml'):
            check_local_ci.check(self.root)

    def test_missing_trigger_fails(self):
        self.workflow.write_text('name: missing\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            check_local_ci.check(self.root)

    def test_divergent_instruction_copy_fails(self):
        path = self.root / 'CLAUDE.md'
        path.unlink()
        path.write_text('duplicate', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CLAUDE.md'):
            check_local_ci.check(self.root)

    def test_absolute_instruction_link_fails(self):
        path = self.root / 'CLAUDE.md'
        path.unlink()
        path.symlink_to(self.root / 'AGENTS.md')
        with self.assertRaisesRegex(ValueError, 'CLAUDE.md'):
            check_local_ci.check(self.root)

    def test_broken_skill_source_fails(self):
        (self.root / '.agents/skills/repo-sync/SKILL.md').unlink()
        with self.assertRaisesRegex(ValueError, 'missing canonical'):
            check_local_ci.check(self.root)


if __name__ == '__main__':
    unittest.main()
