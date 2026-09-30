import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


SPEC = importlib.util.spec_from_file_location("copilot", Path(__file__).parents[1] / "copilot.py")
copilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(copilot)


def main():
    with tempfile.TemporaryDirectory(prefix="zai-copilot-smoke-") as temporary:
        root = Path(temporary)
        copilot.write_private(root / "credentials" / "access-token", "smoke-only-not-a-real-token")
        copilot.write_private(root / "credentials" / "api-key.json", json.dumps({
            "token": "smoke-only-not-a-real-token", "expires_at": time.time() + 3600,
            "endpoints": {"api": "https://api.githubcopilot.com"},
        }))
        config = copilot.proxy_config("gpt-smoke")
        config["model_list"][0]["litellm_params"]["mock_tool_calls"] = [{
            "id": "call_smoke", "type": "function", "function": {"name": "list_files", "arguments": "{}"},
        }]
        copilot.write_private(root / "config.json", json.dumps(config))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        key = "sk-" + secrets.token_urlsafe(32)
        executable = Path(sys.executable).with_name("litellm.exe" if os.name == "nt" else "litellm")
        with (root / "proxy.log").open("w+") as log:
            process = subprocess.Popen(
                [str(executable), "--config", str(root / "config.json"), "--host", "127.0.0.1", "--port", str(port), "--telemetry", "False"],
                env=copilot.proxy_environment(root / "credentials", key), cwd=root, stdout=log, stderr=log,
            )
            try:
                copilot.wait_ready(process, base, key)
                for headers, expected_status in [({}, 401), ({"Authorization": "Bearer wrong-key"}, 400)]:
                    try:
                        request = urllib.request.Request(base + "/v1/models", headers=headers)
                        urllib.request.urlopen(request, timeout=10)
                        raise AssertionError("Gateway accepted an unauthorized request")
                    except urllib.error.HTTPError as error:
                        assert error.code == expected_status, error.code
                payload = {"model": "gpt-smoke", "max_tokens": 32, "messages": [{"role": "user", "content": "hello"}]}
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
                response = copilot.request_json(base + "/v1/messages", payload, headers)
                assert response["type"] == "message", response
                assert any(block.get("name") == "list_files" for block in response["content"]), response
                payload["stream"] = True
                request = urllib.request.Request(base + "/v1/messages", data=json.dumps(payload).encode(), headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    events = response.read().decode()
                    assert "message_start" in events and "message_stop" in events, events
                    text = ""
                    for line in events.splitlines():
                        if line.startswith("data: {"):
                            event = json.loads(line[6:])
                            text += event.get("delta", {}).get("text", "")
                    assert text == "This is a mock request", events
                print("Live gateway authentication and Anthropic Messages JSON/SSE smoke checks passed (mock model, no account).")
            except Exception:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                copilot.stop_process(process)


if __name__ == "__main__":
    main()
