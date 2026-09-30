from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_mods


class ModRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mod-runner-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for mod in ('agents-md', 'sec-default', 'telemetry'):
            tests = self.root / 'mods' / mod / 'tests'
            tests.mkdir(parents=True)
            (tests / 'enabled.test.ts').write_text('enabled', encoding='utf-8')
        self.disabled = self.root / check_mods.DISABLED_REGISTER
        self.disabled.write_text('retained registration test source', encoding='utf-8')
        root_patch = patch.object(check_mods, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def test_reports_quarantine_but_runs_every_mod(self):
        output = io.StringIO()
        with patch.object(check_mods.shutil, 'which', return_value='/fixture/claude'), \
                patch.object(check_mods.subprocess, 'check_output', return_value='2.1.284\n'), \
                patch.object(check_mods.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
                redirect_stdout(output):
            self.assertEqual(check_mods.main(), 0)
        self.assertIn('DISABLED (not a pass)', output.getvalue())
        self.assertIn(check_mods.DISABLED_REGISTER, output.getvalue())
        self.assertEqual([Path(call.args[0][-1]).name for call in run.call_args_list],
                         ['agents-md', 'sec-default', 'telemetry'])
        self.assertEqual(self.disabled.read_text(), 'retained registration test source')
        self.assertFalse((self.disabled.parent / 'register.test.ts').exists())

    def test_other_failures_are_not_masked(self):
        with patch.object(check_mods.shutil, 'which', return_value='/fixture/claude'), \
                patch.object(check_mods.subprocess, 'check_output', return_value='2.1.284\n'), \
                patch.object(check_mods.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1),
                    subprocess.CompletedProcess([], 0),
                ]) as run, redirect_stdout(io.StringIO()):
            self.assertEqual(check_mods.main(), 1)
        self.assertEqual(run.call_count, 3)

    def test_missing_engine_is_not_a_pass(self):
        with patch.object(check_mods.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'compatible Claude Code'):
                check_mods.main()


if __name__ == '__main__':
    unittest.main()
