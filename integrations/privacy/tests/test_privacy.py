import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


LAUNCHER = Path(__file__).resolve().parents[1] / 'claude.py'
SPEC = importlib.util.spec_from_file_location('privacy_launcher', LAUNCHER)
privacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(privacy)
POLICY = json.loads(privacy.SETTINGS_PATH.read_text(encoding='utf-8'))


class PrivacyTests(unittest.TestCase):
    def test_analytics_error_and_feedback_opt_outs(self):
        for name in ('DISABLE_TELEMETRY', 'DO_NOT_TRACK', 'DISABLE_ERROR_REPORTING',
                     'DISABLE_FEEDBACK_COMMAND', 'DISABLE_BUG_COMMAND',
                     'CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY',
                     'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'):
            with self.subTest(name=name):
                self.assertEqual(POLICY['env'][name], '1')
        self.assertEqual(POLICY['feedbackDrafts'], 'off')
        self.assertEqual(POLICY['feedbackSurveyRate'], 0)
        self.assertEqual(POLICY['env']['CLAUDE_CODE_SEND_FEEDBACK'], '0')
        self.assertEqual(POLICY['env']['CLAUDE_CODE_ENABLE_FEEDBACK_SURVEY_FOR_OTEL'], '0')

    def test_all_exporters_and_content_logging_disabled(self):
        self.assertEqual(POLICY['env']['CLAUDE_CODE_ENABLE_TELEMETRY'], '0')
        self.assertEqual(POLICY['env']['OTEL_SDK_DISABLED'], 'true')
        for signal in ('LOGS', 'METRICS', 'TRACES'):
            self.assertEqual(POLICY['env'][f'OTEL_{signal}_EXPORTER'], 'none')
        for name in ('OTEL_LOG_USER_PROMPTS', 'OTEL_LOG_ASSISTANT_RESPONSES',
                     'OTEL_LOG_TOOL_CONTENT', 'OTEL_LOG_TOOL_DETAILS',
                     'OTEL_LOG_RAW_API_BODIES', 'ENABLE_BETA_TRACING_DETAILED',
                     'ENABLE_ENHANCED_TELEMETRY_BETA',
                     'CLAUDE_CODE_ENHANCED_TELEMETRY_BETA'):
            self.assertEqual(POLICY['env'][name], '0')

    def test_removes_inherited_endpoints_credentials_and_trace_context(self):
        inherited = {
            'OTEL_EXPORTER_OTLP_ENDPOINT': 'https://collector.invalid',
            'OTEL_EXPORTER_OTLP_HEADERS': 'Authorization=fixture-only',
            'OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY': '/fixture/key',
            'OTEL_EXPORTER_PROMETHEUS_PORT': '9464',
            'OTEL_FUTURE_VARIABLE': 'unknown',
            'TRACEPARENT': 'fixture', 'TRACESTATE': 'fixture',
            'BETA_TRACING_ENDPOINT': 'https://collector.invalid',
        }
        result = privacy.privacy_environment(inherited, POLICY)
        for name in inherited:
            self.assertIn(result.get(name), (None, ''))
        self.assertEqual(inherited['OTEL_FUTURE_VARIABLE'], 'unknown')

    def test_overrides_conflicting_flags(self):
        inherited = {name: 'conflicting' for name in POLICY['env']}
        self.assertEqual(privacy.privacy_environment(inherited, POLICY), POLICY['env'])

    def test_preserves_provider_authentication_and_nontelemetry_environment(self):
        inherited = {
            'ANTHROPIC_API_KEY': 'fixture-only',
            'ANTHROPIC_BASE_URL': 'http://127.0.0.1:1234',
            'CLAUDE_CODE_USE_BEDROCK': '1', 'PATH': '/fixture', 'HOME': '/fixture',
        }
        result = privacy.privacy_environment(inherited, POLICY)
        for name, value in inherited.items():
            self.assertEqual(result[name], value)

    def test_argument_and_settings_propagation(self):
        arguments = ['-p', 'spaces; $(not-a-shell-command)', '--model', 'fixture-model']
        command = privacy.launch_command(sys.executable, arguments, POLICY, os.environ)
        self.assertEqual(command[1], '--settings')
        self.assertEqual(json.loads(command[2]), POLICY)
        self.assertEqual(command[3:], arguments)

    def test_rejects_settings_replacement(self):
        for option in ('--settings', '--settings={}', '--setting-sources',
                       '--setting-sources=user'):
            with self.subTest(option=option), self.assertRaises(ValueError):
                privacy.launch_command(sys.executable, [option], POLICY, os.environ)

    def test_missing_executable_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            privacy.launch_command('missing-zai-fixture-executable', [], POLICY, {})

    def test_exec_receives_private_environment_and_inherits_terminal(self):
        with patch.object(privacy.os, 'execvpe') as execute:
            privacy.main(['--claude-binary', sys.executable, '--', '--resume'])
        executable, command, environment = execute.call_args.args
        self.assertEqual(command[0], executable)
        self.assertEqual(command[-1], '--resume')
        for name, value in POLICY['env'].items():
            self.assertEqual(environment[name], value)

    def test_unreadable_policy_never_starts_claude(self):
        with patch.object(Path, 'read_text', side_effect=OSError('fixture failure')):
            with patch.object(privacy.os, 'execvpe') as execute:
                self.assertEqual(privacy.main([]), 1)
                execute.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'executable script fixture needs POSIX')
    def test_real_child_keeps_arguments_working_directory_and_exit_status(self):
        with tempfile.TemporaryDirectory(prefix='zai-privacy-test-') as temporary:
            executable = Path(temporary) / 'fixture-claude'
            executable.write_text(
                f'#!{sys.executable}\n'
                'import json, os, sys\n'
                'settings = json.loads(sys.argv[2])\n'
                'print(json.dumps({"args": sys.argv[3:], "cwd": os.getcwd(), '
                '"settings": settings, "env": {name: os.environ.get(name) '
                'for name in settings["env"]}, '
                '"endpoint": os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")}))\n'
                'sys.exit(23)\n', encoding='utf-8',
            )
            executable.chmod(0o700)
            result = subprocess.run(
                [sys.executable, '-B', str(LAUNCHER), '--claude-binary', str(executable),
                 '--', '-p', 'spaces; $(not-a-shell-command)'],
                cwd=temporary, capture_output=True, text=True, timeout=10,
                env={**os.environ, 'OTEL_EXPORTER_OTLP_ENDPOINT': 'https://fixture.invalid'},
            )
            self.assertEqual(result.returncode, 23, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output['cwd'], temporary)
            self.assertEqual(output['args'], ['-p', 'spaces; $(not-a-shell-command)'])
            self.assertEqual(output['settings'], POLICY)
            self.assertEqual(output['env'], POLICY['env'])
            self.assertIsNone(output['endpoint'])

    @unittest.skipUnless(os.name == 'posix', 'PTY test needs POSIX')
    def test_tui_child_inherits_a_real_terminal_without_output_staging(self):
        import pty

        with tempfile.TemporaryDirectory(prefix='zai-privacy-pty-') as temporary:
            executable = Path(temporary) / 'fixture-tui'
            executable.write_text(
                f'#!{sys.executable}\n'
                'import os\n'
                'print("TTY=" + str(all(os.isatty(fd) for fd in (0, 1, 2))))\n',
                encoding='utf-8',
            )
            executable.chmod(0o700)
            master, slave = pty.openpty()
            try:
                result = subprocess.run(
                    [sys.executable, '-B', str(LAUNCHER), '--claude-binary', str(executable)],
                    stdin=slave, stdout=slave, stderr=slave, timeout=10, cwd=temporary,
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn(b'TTY=True', os.read(master, 4096))
                self.assertEqual(sorted(Path(temporary).iterdir()), [executable])
            finally:
                os.close(slave)
                os.close(master)


if __name__ == '__main__':
    unittest.main()
