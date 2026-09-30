import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


privacy = load_module('privacy', ROOT / 'integrations/privacy/claude.py')
copilot = load_module('copilot', ROOT / 'integrations/github-copilot/copilot.py')
with patch.dict(sys.modules, privacy=privacy, copilot=copilot):
    launcher = load_module('installed_claude', ROOT / 'integrations/installer/claude.py')
SETTINGS = json.loads((ROOT / '.claude/settings.json').read_text())


class ClaudeLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zai-claude-dispatch-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / 'runtime.json').write_text(json.dumps({'claude_binary': sys.executable}))
        (self.directory / 'settings.json').write_text(json.dumps(SETTINGS))
        self.patch = patch.object(launcher, 'DIRECTORY', self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_native_commands_and_interactive_start_are_forwarded(self):
        for arguments in ([], ['--help'], ['--version'], ['--resume'], ['--continue'],
                          ['auth', 'login'], ['plugin', 'test', 'fixture'],
                          ['-p', 'spaces; $(not a command)', '--output-format', 'json']):
            with self.subTest(arguments=arguments), patch.object(launcher.os, 'execve') as execute, \
                    patch.object(copilot, 'run') as gateway:
                self.assertEqual(launcher.main(arguments), 0)
                binary, command, environment = execute.call_args.args
                self.assertEqual(binary, sys.executable)
                expected = ([sys.executable, *arguments] if arguments[:2] == ['plugin', 'test'] else
                            [sys.executable, '--settings', json.dumps(SETTINGS), *arguments])
                self.assertEqual(command, expected)
                for name, value in SETTINGS['env'].items():
                    self.assertEqual(environment[name], value)
                gateway.assert_not_called()

    def test_custom_settings_survive_without_disabling_privacy(self):
        custom = {'permissions': {'allow': ['Read']}, 'env': {'CUSTOM': 'keep', 'DISABLE_TELEMETRY': '0'}}
        for option in (['--settings', json.dumps(custom)], ['--settings=' + json.dumps(custom)]):
            command = launcher.configured_arguments([*option, '--resume'], SETTINGS)
            merged = json.loads(command[1])
            self.assertEqual(merged['permissions'], custom['permissions'])
            self.assertEqual(merged['env']['CUSTOM'], 'keep')
            self.assertEqual(merged['env']['DISABLE_TELEMETRY'], '1')
            self.assertEqual(command[2:], ['--resume'])
        path = self.directory / 'custom.json'
        path.write_text(json.dumps(custom))
        self.assertEqual(json.loads(launcher.configured_arguments(['--settings', str(path)], SETTINGS)[1])['permissions'],
                         custom['permissions'])

    def test_native_auth_environment_is_preserved_and_otel_is_removed(self):
        with patch.dict(os.environ, ANTHROPIC_API_KEY='fixture-only',
                        OTEL_EXPORTER_OTLP_ENDPOINT='https://invalid.example'), \
                patch.object(launcher.os, 'execve') as execute:
            launcher.main([])
        environment = execute.call_args.args[2]
        self.assertEqual(environment['ANTHROPIC_API_KEY'], 'fixture-only')
        self.assertNotIn('OTEL_EXPORTER_OTLP_ENDPOINT', environment)

    def test_custom_settings_are_private_not_in_process_arguments_and_are_cleaned(self):
        paths = []
        custom = {'env': {'CUSTOM_SECRET': 'fixture-secret'}, 'permissions': {'allow': ['Read']}}
        def native(command, **kwargs):
            path = Path(command[command.index('--settings') + 1])
            paths.append(path)
            self.assertNotIn('fixture-secret', repr(command))
            self.assertEqual(json.loads(path.read_text())['env']['CUSTOM_SECRET'], 'fixture-secret')
            self.assertEqual(kwargs['env']['DISABLE_TELEMETRY'], '1')
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return subprocess.CompletedProcess(command, 7)
        with patch.object(launcher.subprocess, 'run', side_effect=native):
            self.assertEqual(launcher.main(['--settings', json.dumps(custom)]), 7)
        self.assertFalse(paths[0].parent.exists())

    def test_copilot_namespace_supports_cli_and_tui_login(self):
        for arguments in (['login'], ['login', '--tui'], ['models'], ['logout']):
            with patch.object(copilot, 'main', return_value=0) as gateway, \
                    patch.object(launcher.os, 'execve') as execute:
                self.assertEqual(launcher.main(['copilot', *arguments]), 0)
                gateway.assert_called_once_with(arguments)
                execute.assert_not_called()

    def test_copilot_model_starts_native_ui_without_recursive_routing(self):
        for option in (['--model', 'github-copilot/model-id'], ['--model=github-copilot/model-id']):
            with patch.object(copilot, 'run', return_value=7) as gateway:
                self.assertEqual(launcher.main([*option, '--resume']), 7)
                state, model, command = gateway.call_args.args
                self.assertEqual(state, copilot.DEFAULT_STATE)
                self.assertEqual(model, 'model-id')
                self.assertEqual(launcher.copilot_arguments(command)[0], None)
                self.assertIn('--resume', command)

    def test_end_of_options_preserves_prompt_and_last_native_model_wins(self):
        arguments = ['--', '--model=github-copilot/not-a-model']
        self.assertEqual(launcher.copilot_arguments(arguments), (None, arguments))
        self.assertEqual(launcher.configured_arguments(arguments, SETTINGS)[2:], arguments)
        self.assertEqual(launcher.native_arguments(arguments, 'settings'),
                         ['--settings', 'settings', *arguments])
        self.assertIsNone(launcher.copilot_arguments(['--model', 'github-copilot/one', '--model', 'sonnet'])[0])

    def test_missing_runtime_fails_closed(self):
        (self.directory / 'runtime.json').unlink()
        with patch.object(launcher.os, 'execve') as execute:
            self.assertEqual(launcher.main([]), 1)
            execute.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Executable fixture requires POSIX')
    def test_real_child_keeps_working_directory_arguments_and_exit_status(self):
        native = self.directory / 'native'
        native.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                          'print(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), '
                          '"privacy": os.environ["DISABLE_TELEMETRY"]}))\nsys.exit(7)\n')
        native.chmod(0o755)
        (self.directory / 'runtime.json').write_text(json.dumps({'claude_binary': str(native)}))
        for source, target in (('integrations/installer/claude.py', 'claude.py'),
                               ('integrations/privacy/claude.py', 'privacy.py'),
                               ('integrations/github-copilot/copilot.py', 'copilot.py')):
            shutil.copyfile(ROOT / source, self.directory / target)
        result = subprocess.run([sys.executable, '-B', str(self.directory / 'claude.py'),
                                 '-p', 'space argument', '--resume'], cwd=self.directory,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        record = json.loads(result.stdout)
        self.assertEqual(record['args'][2:], ['-p', 'space argument', '--resume'])
        self.assertEqual(record['cwd'], str(self.directory))
        self.assertEqual(record['privacy'], '1')
