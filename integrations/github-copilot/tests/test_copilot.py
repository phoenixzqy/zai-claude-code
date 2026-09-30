import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("copilot", Path(__file__).parents[1] / "copilot.py")
copilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(copilot)


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class DeviceLoginTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.display = Mock()
        self.device = {
            "device_code": "private-device-code", "user_code": "PUBLIC-CODE",
            "verification_uri": "https://github.com/login/device", "expires_in": 60, "interval": 2,
        }

    def login(self, responses):
        self.request = Mock(side_effect=[self.device, *responses])
        return copilot.device_login(self.display, self.request, self.clock, self.clock.sleep)

    def test_pending_then_authorized(self):
        self.assertEqual(self.login([{"error": "authorization_pending"}, {"access_token": "secret"}]), "secret")
        self.assertEqual(self.clock.now, 4)
        self.assertEqual(self.request.call_args.args[0], copilot.ACCESS_URL)
        self.assertEqual(self.request.call_args.args[1]["grant_type"], "urn:ietf:params:oauth:grant-type:device_code")
        self.display.close.assert_called_once()

    def test_slow_down_increases_poll_interval(self):
        self.login([{"error": "slow_down"}, {"access_token": "secret"}])
        self.assertEqual(self.clock.now, 9)

    def test_declined_and_expired(self):
        for error in ["access_denied", "expired_token", "unexpected"]:
            with self.subTest(error=error), self.assertRaises(copilot.CopilotError):
                self.login([{"error": error}])

    def test_local_expiry_does_not_poll_after_deadline(self):
        self.device["expires_in"] = 1
        with self.assertRaisesRegex(copilot.CopilotError, "expired"):
            self.login([])
        self.assertEqual(self.request.call_count, 1)

    def test_cancellation_restores_display(self):
        with self.assertRaises(KeyboardInterrupt):
            self.login([KeyboardInterrupt()])
        self.display.close.assert_called_once()

    def test_network_failure_restores_display(self):
        with self.assertRaises(copilot.CopilotError):
            self.login([copilot.CopilotError("network")])
        self.display.close.assert_called_once()

    def test_untrusted_verification_url_rejected(self):
        self.device["verification_uri"] = "https://example.org/login/device"
        with self.assertRaisesRegex(copilot.CopilotError, "verification"):
            self.login([])
        self.display.show.assert_not_called()

    def test_incomplete_device_response_rejected(self):
        del self.device["device_code"]
        with self.assertRaisesRegex(copilot.CopilotError, "incomplete"):
            self.login([])

    def test_plain_display_does_not_print_private_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            copilot.LoginDisplay().show(self.device, 60)
        self.assertIn("PUBLIC-CODE", output.getvalue())
        self.assertNotIn("private-device-code", output.getvalue())

    def test_cli_and_tui_use_same_login(self):
        for flag, expected in [([], False), (["--tui"], True)]:
            with self.subTest(tui=expected), patch.object(copilot, "login") as login:
                self.assertEqual(copilot.main(["login", *flag]), 0)
                login.assert_called_once_with(copilot.DEFAULT_STATE, expected)

    def test_tui_panel_and_terminal_restoration(self):
        console = Mock(is_terminal=True)
        live = Mock()
        modules = {
            "rich.console": types.SimpleNamespace(Console=Mock(return_value=console)),
            "rich.live": types.SimpleNamespace(Live=Mock(return_value=live)),
            "rich.panel": types.SimpleNamespace(Panel=lambda text, **kwargs: text),
            "rich.text": types.SimpleNamespace(Text=lambda text: text),
        }
        with patch.dict(copilot.sys.modules, modules):
            display = copilot.LoginDisplay(tui=True)
            display.show(self.device, 60)
            display.update(self.device, 59)
            display.close()
        live.start.assert_called_once()
        live.stop.assert_called_once()
        self.assertIn("PUBLIC-CODE", live.update.call_args.args[0])
        self.assertIn("59s", live.update.call_args.args[0])
        self.assertNotIn("private-device-code", live.update.call_args.args[0])

    def test_tui_rejects_noninteractive_output(self):
        modules = {
            "rich.console": types.SimpleNamespace(Console=lambda: Mock(is_terminal=False)),
            "rich.live": types.SimpleNamespace(Live=Mock()),
        }
        with patch.dict(copilot.sys.modules, modules), self.assertRaisesRegex(copilot.CopilotError, "interactive terminal"):
            copilot.LoginDisplay(tui=True).show(self.device, 60)


class CredentialTests(unittest.TestCase):
    def test_private_atomic_write_and_logout(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "credentials"
            copilot.write_private(state / "access-token", "secret")
            copilot.write_private(state / "api-key.json", "{}")
            copilot.write_private(state / "keep", "unrelated")
            if os.name != "nt":
                self.assertEqual(state.stat().st_mode & 0o777, 0o700)
                self.assertEqual((state / "access-token").stat().st_mode & 0o777, 0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(copilot.main(["--state-dir", str(state), "logout"]), 0)
            self.assertEqual(list(state.iterdir()), [state / "keep"])

    def test_failed_login_preserves_existing_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            copilot.write_private(state / "access-token", "old-secret")
            with patch.object(copilot, "device_login", return_value="new-secret"), patch.object(
                    copilot, "exchange_token", side_effect=copilot.CopilotError("no entitlement")):
                with self.assertRaises(copilot.CopilotError):
                    copilot.login(state)
            self.assertEqual((state / "access-token").read_text(), "old-secret")

    def test_successful_login_saves_both_tokens_without_printing(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            output = io.StringIO()
            with patch.object(copilot, "LoginDisplay") as display, patch.object(copilot, "device_login", return_value="github-secret"), patch.object(
                    copilot, "exchange_token", return_value={"token": "copilot-secret"}), contextlib.redirect_stdout(output):
                copilot.login(state, tui=True)
            display.assert_called_once_with(True)
            self.assertEqual((state / "access-token").read_text(), "github-secret")
            self.assertEqual(json.loads((state / "api-key.json").read_text())["token"], "copilot-secret")
            self.assertNotIn("secret", output.getvalue())

    def test_symlink_credential_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link").symlink_to(root, target_is_directory=True)
            with self.assertRaises(copilot.CopilotError):
                copilot.write_private(root / "link" / "access-token", "secret")

    def test_missing_login_is_actionable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(copilot.CopilotError, "login --tui"):
                copilot.session(Path(temporary))

    def test_exchange_checks_entitlement_and_endpoint(self):
        for response in [{}, {"token": "secret", "expires_at": 1}, {
                "token": "secret", "expires_at": 9999999999, "endpoints": {"api": "https://evil.example"}}]:
            with self.subTest(response=response), self.assertRaises(copilot.CopilotError):
                copilot.exchange_token("github-secret", Mock(return_value=response))

    def test_exchange_accepts_valid_token(self):
        response = {"token": "secret", "expires_at": 9999999999, "endpoints": {"api": "https://api.githubcopilot.com"}}
        request = Mock(return_value=response)
        self.assertEqual(copilot.exchange_token("github-secret", request), response)
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "token github-secret")


class GatewayTests(unittest.TestCase):
    def test_endpoint_allowlist(self):
        for endpoint in ["https://api.githubcopilot.com", "https://api.business.githubcopilot.com/"]:
            self.assertEqual(copilot.validate_api_base(endpoint), endpoint.rstrip("/"))
        for endpoint in ["http://api.githubcopilot.com", "https://evilgithubcopilot.com", "https://githubcopilot.com.evil.example",
                         "https://api.githubcopilot.com@evil.example", "https://api.githubcopilot.com:444", "https://api.githubcopilot.com/other",
                         "https://api.githubcopilot.com?other", "https://api.githubcopilot.com#other"]:
            with self.subTest(endpoint=endpoint), self.assertRaises(copilot.CopilotError):
                copilot.validate_api_base(endpoint)

    def test_redirects_are_rejected(self):
        with self.assertRaises(copilot.CopilotError):
            copilot.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example")

    def test_environment_removes_conflicting_auth_and_cloud_providers(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "real-secret", "CLAUDE_CODE_OAUTH_TOKEN": "other-secret",
                                     "CLAUDE_CODE_USE_BEDROCK": "1", "KEEP": "yes"}, clear=True):
            environment = copilot.claude_environment("http://127.0.0.1:1", "local-secret", "gpt-test")
        self.assertNotIn("ANTHROPIC_API_KEY", environment)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", environment)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", environment)
        self.assertEqual(environment["KEEP"], "yes")
        self.assertEqual(environment["CLAUDE_CODE_SUBAGENT_MODEL"], "gpt-test")
        self.assertEqual(environment["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gpt-test")

    def test_proxy_environment_ignores_credential_endpoint_overrides(self):
        with patch.dict(os.environ, {"GITHUB_COPILOT_API_BASE": "https://evil.example", "GITHUB_COPILOT_API_KEY_URL": "https://evil.example",
                                     "GITHUB_COPILOT_ACCESS_TOKEN_FILE": "/tmp/other", "DATABASE_URL": "unrelated"}, clear=True):
            environment = copilot.proxy_environment(Path("/tmp/example"), "local-secret")
        self.assertNotIn("GITHUB_COPILOT_API_BASE", environment)
        self.assertNotIn("GITHUB_COPILOT_API_KEY_URL", environment)
        self.assertNotIn("GITHUB_COPILOT_ACCESS_TOKEN_FILE", environment)
        self.assertNotIn("DATABASE_URL", environment)
        self.assertEqual(environment["GITHUB_COPILOT_TOKEN_DIR"], "/tmp/example")

    def test_config_uses_copilot_and_authenticated_gateway(self):
        config = copilot.proxy_config("gpt-test")
        self.assertEqual(config["model_list"][0]["litellm_params"]["model"], "github_copilot/gpt-test")
        self.assertEqual(config["general_settings"]["master_key"], "os.environ/COPILOT_LOCAL_KEY")
        self.assertTrue(config["litellm_settings"]["turn_off_message_logging"])
        self.assertFalse(config["litellm_settings"]["telemetry"])

    def test_failed_startup_is_not_reported_ready(self):
        process = Mock()
        process.poll.return_value = 1
        with self.assertRaisesRegex(copilot.CopilotError, "startup"):
            copilot.wait_ready(process, "http://127.0.0.1:1", "local-secret")

    def test_readiness_uses_session_key(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(copilot, "request_json", return_value={"data": [{"id": "model"}]}) as request:
            copilot.wait_ready(process, "http://127.0.0.1:1", "local-secret")
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer local-secret")

    def test_only_owned_process_is_stopped_and_reaped(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("owned", 10), 0]
        copilot.stop_process(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_run_cleanup_after_startup_failure(self):
        process = Mock()
        with patch.object(Path, "is_file", return_value=True), patch.object(copilot.shutil, "which", return_value="claude"), \
                patch.object(copilot, "models", return_value=[{"id": "model", "capabilities": {"supports": {"tool_calls": True}}}]), \
                patch.object(copilot.subprocess, "Popen", return_value=process) as popen, \
                patch.object(copilot, "wait_ready", side_effect=copilot.CopilotError("startup")), \
                patch.object(copilot, "stop_process") as stop:
            with self.assertRaises(copilot.CopilotError):
                copilot.run(Path("/tmp/example"), "model", [])
        stop.assert_called_once_with(process)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertFalse(Path(command[command.index("--config") + 1]).exists())

    def test_run_rejects_non_tool_model_before_starting_proxy(self):
        with patch.object(Path, "is_file", return_value=True), patch.object(copilot.shutil, "which", return_value="claude"), \
                patch.object(copilot, "models", return_value=[{"id": "model"}]), \
                patch.object(copilot.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(copilot.CopilotError, "tool calling"):
                copilot.run(Path("/tmp/example"), "model", [])
        popen.assert_not_called()

    def test_run_passes_arguments_and_cleans_up_on_normal_exit(self):
        gateway = Mock()
        child = Mock()
        child.wait.return_value = 3
        with patch.object(Path, "is_file", return_value=True), patch.object(copilot.shutil, "which", return_value="claude"), \
                patch.object(copilot, "models", return_value=[{"id": "model", "capabilities": {"supports": {"tool_calls": True}}}]), \
                patch.object(copilot.subprocess, "Popen", side_effect=[gateway, child]) as popen, \
                patch.object(copilot, "wait_ready"), patch.object(copilot, "stop_process") as stop, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(copilot.run(Path("/tmp/example"), "model", ["-p", "hello"]), 3)
        self.assertEqual(popen.call_args.args[0], ["claude", "-p", "hello"])
        self.assertEqual([entry.args[0] for entry in stop.call_args_list], [child, gateway])
        self.assertEqual(popen.call_args.kwargs["env"]["ANTHROPIC_MODEL"], "model")
        gateway_call = popen.call_args_list[0]
        self.assertFalse(Path(gateway_call.kwargs["cwd"]).exists())

    def test_main_hides_internal_exception_secrets(self):
        output = io.StringIO()
        with patch.object(copilot, "login", side_effect=ValueError("private-token")), contextlib.redirect_stderr(output):
            self.assertEqual(copilot.main(["login"]), 1)
        self.assertNotIn("private-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
