import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


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

    def test_interactive_native_and_hosted_start_do_not_intercept_login(self):
        for arguments in ([], ['auth', 'login'], ['--session-id', 'fixture', '--add-dir', 'resources',
                          '--append-system-prompt-file', 'instructions.md', '--dangerously-skip-permissions']):
            with self.subTest(arguments=arguments), \
                    patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                    patch.object(copilot, 'login') as login, \
                    patch.object(copilot, 'models') as models, \
                    patch.object(copilot, 'run') as gateway, \
                    patch.object(launcher.os, 'execve') as execute:
                self.assertEqual(launcher.main(arguments), 0)
                self.assertEqual(execute.call_args.args[1][3:], arguments)
                login.assert_not_called()
                models.assert_not_called()
                gateway.assert_not_called()

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
                gateway.assert_called_once_with(arguments, claude_binary=Path(sys.executable),
                                                environment=privacy.privacy_environment(os.environ, SETTINGS))
                execute.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Executable fixture requires POSIX')
    def test_explicit_copilot_model_launches_real_native_child_once(self):
        record = self.directory / 'child.json'
        native = self.directory / 'native'
        native.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                          f'with open({str(record)!r}, "w") as output:\n'
                          ' json.dump({"args": sys.argv[1:], "model": os.environ["ANTHROPIC_MODEL"], '
                          '"privacy": os.environ["DISABLE_TELEMETRY"]}, output)\n'
                          'sys.exit(7)\n')
        native.chmod(0o755)
        (self.directory / 'runtime.json').write_text(json.dumps({'claude_binary': str(native)}))
        (self.directory / 'access-token').write_text('fixture-only')
        (self.directory / 'litellm').write_text('gateway fixture')
        create_process = subprocess.Popen
        gateway = Mock()
        gateway.poll.return_value = None

        def start(command, **options):
            if command[0] == str(self.directory / 'litellm'):
                return gateway
            self.assertEqual(command[0], str(native))
            return create_process(command, **options)

        with patch.object(copilot, 'DEFAULT_STATE', self.directory), \
                patch.object(copilot.sys, 'executable', str(self.directory / 'python')), \
                patch.object(copilot, 'models', return_value=[
                    {'id': 'model-id', 'capabilities': {'supports': {'tool_calls': True}}},
                ]), patch.object(copilot, 'wait_ready'), \
                patch.object(copilot.subprocess, 'Popen', side_effect=start) as start_process:
            self.assertEqual(launcher.main(['--model', 'github-copilot/model-id', '--session-id', 'fixture-session']), 7)
        self.assertEqual(start_process.call_count, 2)
        child = json.loads(record.read_text())
        self.assertEqual(child['args'][2:], ['--model', 'model-id', '--session-id', 'fixture-session'])
        self.assertEqual(child['model'], 'model-id')
        self.assertEqual(child['privacy'], '1')
        gateway.terminate.assert_called_once()

    def test_copilot_model_starts_native_ui_without_recursive_routing(self):
        for option in (['--model', 'github-copilot/model-id'], ['--model=github-copilot/model-id']):
            with patch.object(copilot, 'run', return_value=7) as gateway:
                self.assertEqual(launcher.main([*option, '--resume']), 7)
                state, model, command = gateway.call_args.args
                self.assertEqual(gateway.call_args.kwargs['claude_binary'], Path(sys.executable))
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
