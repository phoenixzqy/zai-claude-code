import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
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

    def test_interactive_start_offers_copilot_and_runs_selected_model(self):
        available = [
            {'id': 'no-tools'},
            {'id': 'model-id', 'capabilities': {'supports': {'tool_calls': True}}},
        ]
        with patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                patch.object(launcher, 'choose', side_effect=[1, 0]) as choose, \
                patch.object(copilot, 'DEFAULT_STATE', self.directory / 'state'), \
                patch.object(copilot, 'login') as login, \
                patch.object(copilot, 'models', return_value=available), \
                patch.object(copilot, 'run', return_value=7) as gateway, \
                patch.object(launcher.os, 'execve') as execute:
            self.assertEqual(launcher.main([]), 7)
            self.assertIn('GitHub Copilot account', choose.call_args_list[0].args[1])
            self.assertEqual(choose.call_args_list[1].args[1], ['model-id'])
            login.assert_called_once_with(self.directory / 'state', tui=True)
            gateway.assert_called_once_with(self.directory / 'state', 'model-id',
                                            ['--settings', json.dumps(SETTINGS)])
            execute.assert_not_called()

    def test_saved_copilot_login_is_reused_but_explicit_login_reauthenticates(self):
        (self.directory / 'access-token').write_text('fixture-only')
        for arguments in ([], ['auth', 'login']):
            with self.subTest(arguments=arguments), \
                    patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                    patch.object(launcher, 'choose', side_effect=[1, 0]), \
                    patch.object(copilot, 'DEFAULT_STATE', self.directory), \
                    patch.object(copilot, 'login') as login, \
                    patch.object(copilot, 'models', return_value=[
                        {'id': 'model-id', 'capabilities': {'supports': {'tool_calls': True}}},
                    ]) as models, \
                    patch.object(copilot, 'run', return_value=0) as gateway, \
                    patch.object(launcher.os, 'execve') as execute:
                self.assertEqual(launcher.main(arguments), 0)
                execute.assert_not_called()
                if arguments:
                    login.assert_called_once_with(self.directory, tui=True)
                    models.assert_not_called()
                    gateway.assert_not_called()
                else:
                    login.assert_not_called()
                    gateway.assert_called_once()

    def test_hosted_interactive_start_offers_copilot_and_preserves_resources(self):
        resources = self.directory / 'resources'
        custom = {'hooks': {'SessionStart': []}, 'env': {'HOST_SETTING': 'keep'}}
        settings = self.directory / 'host-settings.json'
        settings.write_text(json.dumps(custom))
        arguments = ['--add-dir', str(resources), '--append-system-prompt-file',
                     str(resources / 'instructions.md'), '--settings', str(settings),
                     '--dangerously-skip-permissions', '--session-id',
                     '10da8a78-55bd-41c4-aa22-50d410412fca']

        def run(state, model, command):
            self.assertEqual(model, 'model-id')
            snapshot = Path(command[command.index('--settings') + 1])
            merged = json.loads(snapshot.read_text())
            self.assertEqual(merged['hooks'], custom['hooks'])
            self.assertEqual(merged['env']['HOST_SETTING'], 'keep')
            self.assertEqual(merged['env']['DISABLE_TELEMETRY'], '1')
            self.assertEqual(command[2:], arguments[:4] + arguments[6:])
            return 7

        with patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                patch.object(launcher, 'choose', side_effect=[1, 0]) as choose, \
                patch.object(copilot, 'DEFAULT_STATE', self.directory / 'state'), \
                patch.object(copilot, 'login'), \
                patch.object(copilot, 'models', return_value=[
                    {'id': 'model-id', 'capabilities': {'supports': {'tool_calls': True}}},
                ]), patch.object(copilot, 'run', side_effect=run), \
                patch.object(launcher.os, 'execve') as execute:
            self.assertEqual(launcher.main(arguments), 7)
            self.assertIn('GitHub Copilot account', choose.call_args_list[0].args[1])
            execute.assert_not_called()

    def test_host_options_do_not_hide_noninteractive_modes_or_invalid_arguments(self):
        with patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                patch.object(launcher.sys.stdout, 'isatty', return_value=True):
            for arguments in (['--session-id=fixture', '--settings={}'],
                              ['--add-dir', 'resource', '--add-dir', 'other'],
                              ['--settings', '{}', '--dangerously-skip-permissions']):
                with self.subTest(arguments=arguments):
                    self.assertTrue(launcher.interactive_provider(arguments))
            for extra in (['--print'], ['-p', 'prompt'], ['--resume', 'fixture'],
                          ['--continue'], ['--model=sonnet'], ['--model', 'sonnet'],
                          ['auth', 'status'], ['--help'], ['prompt'], ['--', 'prompt'],
                          ['--session-id'], ['--settings='], ['--settings', '--print'],
                          ['--unknown'], ['--dangerously-skip-permissions=true']):
                with self.subTest(extra=extra):
                    self.assertFalse(launcher.interactive_provider(['--session-id', 'fixture', *extra]))

    def test_native_selection_preserves_startup_and_auth_login(self):
        for arguments in ([], ['auth', 'login']):
            with self.subTest(arguments=arguments), \
                    patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                    patch.object(launcher, 'choose', return_value=0), \
                    patch.object(copilot, 'login') as login, \
                    patch.object(launcher.os, 'execve') as execute:
                self.assertEqual(launcher.main(arguments), 0)
                self.assertEqual(execute.call_args.args[1][3:], arguments)
                login.assert_not_called()

    def test_picker_does_not_intercept_native_flags_commands_or_piped_input(self):
        for arguments in (['--resume'], ['--continue'], ['--help'], ['--version'],
                          ['-p', 'prompt'], ['prompt'], ['--model', 'sonnet'],
                          ['plugin', 'test', 'fixture']):
            with self.subTest(arguments=arguments), \
                    patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                    patch.object(launcher, 'choose') as choose, \
                    patch.object(launcher.os, 'execve'):
                self.assertEqual(launcher.main(arguments), 0)
                choose.assert_not_called()
        for stdin, stdout in ((False, True), (True, False), (False, False)):
            with self.subTest(stdin=stdin, stdout=stdout), \
                    patch.object(launcher.sys.stdin, 'isatty', return_value=stdin), \
                    patch.object(launcher.sys.stdout, 'isatty', return_value=stdout), \
                    patch.object(launcher, 'choose') as choose, \
                    patch.object(launcher.os, 'execve'):
                self.assertEqual(launcher.main([]), 0)
                choose.assert_not_called()

    def test_picker_cancellation_and_login_failure_do_not_launch_native(self):
        for error, expected in ((KeyboardInterrupt(), 130), (copilot.CopilotError('Declined'), 1)):
            with self.subTest(error=error), \
                    patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch.object(launcher.sys.stdout, 'isatty', return_value=True), \
                    patch.object(launcher, 'choose', side_effect=error), \
                    patch.object(launcher.os, 'execve') as execute, \
                    patch.object(copilot, 'run') as gateway:
                self.assertEqual(launcher.main([]), expected)
                execute.assert_not_called()
                gateway.assert_not_called()

    def test_picker_keyboard_navigation_and_cancellation(self):
        for keys, expected in ((['down', '\r'], 1), (['up', '\n'], 2),
                               (['3', '\r'], 2), (['x', 'j', 'k', '\r'], 0)):
            with self.subTest(keys=keys), patch.object(launcher, 'terminal_keys') as keyboard:
                keyboard.return_value.__enter__.return_value.side_effect = keys
                self.assertEqual(launcher.choose('Fixture picker', ['one', 'two', 'three']), expected)
        for key in ('\x1b', '\x03', 'q'):
            with self.subTest(key=key), patch.object(launcher, 'terminal_keys') as keyboard:
                keyboard.return_value.__enter__.return_value.return_value = key
                with self.assertRaises(KeyboardInterrupt):
                    launcher.choose('Fixture picker', ['one'])
                keyboard.return_value.__exit__.assert_called_once()
        with self.assertRaisesRegex(copilot.CopilotError, 'No tool-calling models'):
            launcher.choose('Models', [])

    def test_windows_keyboard_handles_extended_arrow_keys(self):
        keyboard = Mock()
        keyboard.getwch.side_effect = ['\xe0', 'P', '\x00', 'H', '\r', '\x1b']
        with patch.object(launcher.os, 'name', 'nt'), patch.dict(sys.modules, msvcrt=keyboard):
            with launcher.terminal_keys() as read_key:
                self.assertEqual([read_key() for _ in range(4)], ['down', 'up', '\r', '\x1b'])

    @unittest.skipUnless(os.name == 'posix', 'PTY regression requires POSIX')
    def test_real_terminal_startup_selects_copilot_and_restores_terminal(self):
        import fcntl
        import pty
        import select
        import struct
        import termios

        script = self.directory / 'terminal_fixture.py'
        script.write_text(
            'import sys\nfrom unittest.mock import patch\n'
            f'sys.path.insert(0, {str(ROOT / "integrations/installer/tests")!r})\n'
            'from test_claude import launcher, copilot\n'
            f'launcher.DIRECTORY = launcher.Path({str(self.directory)!r})\n'
            'def login(state, tui=False):\n'
            '    assert tui\n    print("DEVICE_LOGIN_TUI", flush=True)\n'
            'def run(state, model, command):\n'
            '    assert model == "fixture-model"\n'
            '    print("COPILOT_NATIVE_UI", flush=True)\n    return 7\n'
            'copilot.login = login\ncopilot.run = run\n'
            f'copilot.DEFAULT_STATE = launcher.Path({str(self.directory / "state")!r})\n'
            'copilot.models = lambda state: [{"id": "fixture-model", '
            '"capabilities": {"supports": {"tool_calls": True}}}]\n'
            'sys.exit(launcher.main(sys.argv[1:]))\n'
        )
        for arguments, cancel in (([], False), ([], True),
                                  (['--add-dir', str(self.directory),
                                    '--append-system-prompt-file', str(self.directory / 'instructions.md'),
                                    '--settings', '{}', '--dangerously-skip-permissions',
                                    '--session-id', '10da8a78-55bd-41c4-aa22-50d410412fca'], False)):
            with self.subTest(arguments=arguments, cancel=cancel):
                master, slave = pty.openpty()
                original = termios.tcgetattr(slave)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
                process = subprocess.Popen(
                    [sys.executable, '-B', str(script), *arguments], stdin=slave, stdout=slave, stderr=slave,
                    env={**os.environ, 'TERM': 'xterm-256color', 'NO_COLOR': '1'},
                )
                output = b''

                def read_until(expected):
                    nonlocal output
                    deadline = time.monotonic() + 10
                    while expected not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            output += os.read(master, 65536)
                    self.assertIn(expected, output)

                try:
                    read_until(b'GitHub Copilot account')
                    os.write(master, b'\x1b' if cancel else b'\x1b[B\r')
                    if not cancel:
                        read_until(b'Select GitHub Copilot model')
                        self.assertIn(b'DEVICE_LOGIN_TUI', output)
                        os.write(master, b'\r')
                        read_until(b'COPILOT_NATIVE_UI')
                    read_until(b'\x1b[?1049l')
                    self.assertEqual(process.wait(timeout=10), 130 if cancel else 7)
                    self.assertEqual(termios.tcgetattr(slave), original)
                    self.assertIn(b'\x1b[?1049l', output)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
                    os.close(master)
                    os.close(slave)

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
