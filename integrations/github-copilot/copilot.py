import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


CLIENT_ID = "Iv1.b507a08c87ecfe98"
DEVICE_URL = "https://github.com/login/device/code"
ACCESS_URL = "https://github.com/login/oauth/access_token"
TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_STATE = Path.home() / ".config" / "zai-claude-code" / "copilot"


class CopilotError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise CopilotError("Unexpected redirect from the authentication service.")


def request_json(url, data=None, headers=None):
    request_headers = {"Accept": "application/json", **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise CopilotError(f"GitHub returned HTTP {error.code}; check your Copilot entitlement and organization policy.") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise CopilotError("Could not read the GitHub response; check your network and retry.") from None


def secure_directory(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise CopilotError("Credential directory must not be a symbolic link.")
    directory.chmod(0o700)


def write_private(path, content):
    secure_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_api_base(base):
    parsed = urllib.parse.urlsplit(base)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or not (host == "api.githubcopilot.com" or host.endswith(".githubcopilot.com"))
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise CopilotError("GitHub returned an untrusted Copilot API endpoint.")
    return base.rstrip("/")


class LoginDisplay:
    def __init__(self, tui=False):
        self.tui = tui
        self.live = None
        if not tui:
            return
        try:
            from rich.console import Console
            from rich.live import Live
        except ImportError:
            raise CopilotError("Install requirements.txt to use the TUI login.") from None
        console = Console()
        if not console.is_terminal:
            raise CopilotError("TUI login requires an interactive terminal; use login without --tui instead.")
        self.live = Live(console=console, screen=True, refresh_per_second=4)

    def show(self, device, remaining):
        if not self.tui:
            print(f"Open {device['verification_uri']} and enter code {device['user_code']}.", flush=True)
            print("Waiting for authorization. Press Ctrl-C to cancel.", flush=True)
            return
        self.live.start()
        self.update(device, remaining)

    def update(self, device, remaining):
        if self.live:
            from rich.panel import Panel
            from rich.text import Text
            text = Text(f"Open: {device['verification_uri']}\n\nCode: {device['user_code']}\n\nWaiting for GitHub authorization ({int(remaining)}s remaining).\n\nPress Ctrl-C to cancel.")
            self.live.update(Panel(text, title="GitHub Copilot login", border_style="blue"))

    def close(self):
        if self.live:
            self.live.stop()


def device_login(display, request=request_json, clock=time.monotonic, sleep=time.sleep):
    device = request(DEVICE_URL, {"client_id": CLIENT_ID, "scope": "read:user"})
    required = ("device_code", "user_code", "verification_uri", "expires_in")
    if not all(device.get(field) for field in required):
        raise CopilotError("GitHub returned an incomplete device authorization response.")
    if device["verification_uri"] != "https://github.com/login/device":
        raise CopilotError("GitHub returned an unexpected verification URL.")
    interval = max(1, int(device.get("interval", 5)))
    deadline = clock() + int(device["expires_in"])
    try:
        display.show(device, deadline - clock())
        while clock() < deadline:
            next_poll = min(clock() + interval, deadline)
            while clock() < next_poll:
                display.update(device, deadline - clock())
                sleep(min(1, next_poll - clock()))
            if clock() >= deadline:
                break
            response = request(ACCESS_URL, {
                "client_id": CLIENT_ID,
                "device_code": device["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
            if response.get("access_token"):
                return response["access_token"]
            error = response.get("error")
            if error == "slow_down":
                interval += 5
            elif error == "authorization_pending":
                continue
            elif error == "access_denied":
                raise CopilotError("GitHub authorization was declined.")
            elif error == "expired_token":
                break
            else:
                raise CopilotError("GitHub device authorization failed; restart login.")
        raise CopilotError("GitHub device code expired; restart login.")
    finally:
        display.close()


def exchange_token(access_token, request=request_json):
    response = request(TOKEN_URL, headers={
        "Authorization": f"token {access_token}",
        "Editor-Version": "vscode/1.95.0",
        "Editor-Plugin-Version": "copilot-chat/0.26.7",
        "User-Agent": "GitHubCopilotChat/0.26.7",
    })
    if not response.get("token") or response.get("expires_at", 0) <= time.time():
        raise CopilotError("No usable Copilot token returned; an active Copilot subscription is required.")
    validate_api_base(response.get("endpoints", {}).get("api", "https://api.githubcopilot.com"))
    return response


def login(state, tui=False):
    access_token = device_login(LoginDisplay(tui))
    api_key = exchange_token(access_token)
    write_private(state / "access-token", access_token)
    write_private(state / "api-key.json", json.dumps(api_key))
    print("Logged in to GitHub Copilot. Use models to see your available models.")


def session(state):
    try:
        access_token = (state / "access-token").read_text().strip()
    except FileNotFoundError:
        raise CopilotError("Not logged in. Run login or login --tui first.") from None
    if not access_token:
        raise CopilotError("Empty credentials. Run login again.")
    api_key = exchange_token(access_token)
    write_private(state / "api-key.json", json.dumps(api_key))
    return api_key


def models(state):
    api_key = session(state)
    base = validate_api_base(api_key.get("endpoints", {}).get("api", "https://api.githubcopilot.com"))
    response = request_json(base + "/models", headers={
        "Authorization": f"Bearer {api_key['token']}",
        "Copilot-Integration-Id": "vscode-chat",
        "Editor-Version": "vscode/1.95.0",
        "Editor-Plugin-Version": "copilot-chat/0.26.7",
        "User-Agent": "GitHubCopilotChat/0.26.7",
    })
    return response.get("data", [])


def proxy_config(model):
    return {
        "model_list": [{"model_name": model, "litellm_params": {"model": f"github_copilot/{model}"}}],
        "litellm_settings": {
            "telemetry": False, "turn_off_message_logging": True, "set_verbose": False,
            "disable_copilot_system_to_assistant": True,
        },
        "general_settings": {"master_key": "os.environ/COPILOT_LOCAL_KEY", "disable_spend_logs": True},
    }


def proxy_environment(state, key):
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith(("GITHUB_COPILOT_", "LITELLM_"))
                   and name not in ("DATABASE_URL", "STORE_MODEL_IN_DB", "CONFIG_FILE_PATH")}
    environment.update({
        "GITHUB_COPILOT_TOKEN_DIR": str(state.resolve()),
        "COPILOT_LOCAL_KEY": key,
        "LITELLM_LOG": "ERROR",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    })
    return environment


def claude_environment(base, key, model, environment=None):
    environment = {name: value for name, value in (os.environ if environment is None else environment).items()
                   if not name.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_OAUTH_TOKEN"))}
    environment.update({
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_AUTH_TOKEN": key,
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    return environment


def wait_ready(process, base, key, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CopilotError("Copilot gateway exited during startup; verify the pinned dependencies are installed.")
        try:
            response = request_json(base + "/v1/models", headers={"Authorization": f"Bearer {key}"})
            if response.get("data"):
                return
        except CopilotError:
            pass
        time.sleep(0.2)
    raise CopilotError("Copilot gateway did not become ready in time.")


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def native_claude(binary=None):
    candidate = str(binary) if binary is not None else shutil.which("claude")
    if not candidate:
        raise CopilotError("Install Claude Code first.")

    def is_launcher(path):
        with Path(path).open("rb") as source:
            source.seek(max(0, Path(path).stat().st_size - 65536))
            return b"ZAI_CLAUDE_CODE_LAUNCHER=1" in source.read()

    if binary is None and is_launcher(candidate):
        runtime = Path.home() / ".local" / "share" / "zai-claude-code" / "runtime.json"
        candidate = json.loads(runtime.read_text())["claude_binary"]
    if not Path(candidate).is_absolute() or not Path(candidate).is_file() or is_launcher(candidate):
        raise CopilotError("Native Claude executable is missing or recursive; rerun the install script.")
    return candidate


def run(state, model, arguments, claude_binary=None, environment=None):
    executable = Path(sys.executable).with_name("litellm.exe" if os.name == "nt" else "litellm")
    claude = native_claude(claude_binary)
    if not executable.is_file():
        raise CopilotError("Install requirements.txt in this Python environment and install Claude Code first.")
    available = models(state)
    selected = next((entry for entry in available if entry.get("id") == model), None)
    if selected is None:
        raise CopilotError("Model not available to this account. Run models and use an exact model ID.")
    if not selected.get("capabilities", {}).get("supports", {}).get("tool_calls"):
        raise CopilotError("This model does not advertise tool calling, which Claude Code needs.")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    key = "sk-" + secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="zai-copilot-") as temporary:
        config = Path(temporary) / "config.json"
        write_private(config, json.dumps(proxy_config(model)))
        gateway = subprocess.Popen(
            [str(executable), "--config", str(config), "--host", "127.0.0.1", "--port", str(port), "--telemetry", "False"],
            env=proxy_environment(state, key), cwd=temporary, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            wait_ready(gateway, base, key)
            print(f"Using GitHub Copilot model {model} through a loopback-only gateway.", flush=True)
            child = subprocess.Popen([claude, *arguments], env=claude_environment(base, key, model, environment))
            try:
                return child.wait()
            finally:
                stop_process(child)
        finally:
            stop_process(gateway)


def main(argv=None, claude_binary=None, environment=None):
    parser = argparse.ArgumentParser(description="GitHub Copilot device login and Claude Code gateway")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    commands = parser.add_subparsers(dest="command", required=True)
    login_parser = commands.add_parser("login", help="Log in with a GitHub device code")
    login_parser.add_argument("--tui", action="store_true", help="Show a full-screen terminal login panel")
    commands.add_parser("logout", help="Delete this integration's locally saved tokens")
    commands.add_parser("models", help="List models available to your Copilot account")
    run_parser = commands.add_parser("run", help="Launch Claude Code through a private Copilot gateway")
    run_parser.add_argument("--model", required=True, help="Exact model ID from models")
    run_parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            login(args.state_dir, args.tui)
        elif args.command == "logout":
            for name in ("access-token", "api-key.json"):
                (args.state_dir / name).unlink(missing_ok=True)
            print("Local Copilot tokens removed. Revoke the GitHub OAuth authorization separately if needed.")
        elif args.command == "models":
            for entry in models(args.state_dir):
                print(entry["id"])
        elif args.command == "run":
            arguments = args.claude_args
            if arguments[:1] == ["--"]:
                arguments = arguments[1:]
            return run(args.state_dir, args.model, arguments, claude_binary=claude_binary, environment=environment)
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except (CopilotError, OSError, ValueError, TypeError, KeyError) as error:
        message = str(error) if isinstance(error, CopilotError) else "Invalid response or local configuration; check permissions and retry."
        print(f"Error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
