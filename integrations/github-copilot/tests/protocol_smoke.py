import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch


os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import httpx
import litellm
from openai import AsyncOpenAI
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler


async def main():
    litellm.telemetry = False
    litellm.turn_off_message_logging = True
    litellm.disable_copilot_system_to_assistant = True
    observed = []

    def upstream(request):
        assert request.url.host == "api.githubcopilot.com", request.url
        assert request.headers["authorization"] == "Bearer smoke-only-not-a-real-token"
        body = json.loads(request.content)
        observed.append((request.url.path, body))
        if request.url.path == "/v1/messages":
            response = {
                "id": "msg_smoke", "type": "message", "role": "assistant", "model": body["model"],
                "content": [{"type": "tool_use", "id": "call_smoke", "name": "list_files", "input": {}}],
                "stop_reason": "tool_use", "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        else:
            assert request.url.path == "/chat/completions", request.url
            assert body["messages"][0]["role"] == "system", body
            response = {
                "id": "chat_smoke", "object": "chat.completion", "created": 1, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [{
                        "id": "call_smoke", "type": "function", "function": {"name": "list_files", "arguments": "{}"},
                    }],
                }}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        return httpx.Response(200, json=response)

    with tempfile.TemporaryDirectory(prefix="zai-copilot-protocol-") as temporary:
        root = Path(temporary)
        (root / "access-token").write_text("smoke-only-not-a-real-token")
        (root / "api-key.json").write_text(json.dumps({
            "token": "smoke-only-not-a-real-token", "expires_at": time.time() + 3600,
            "endpoints": {"api": "https://api.githubcopilot.com"},
        }))
        environment = {name: value for name, value in os.environ.items() if not name.startswith("GITHUB_COPILOT_")}
        environment["GITHUB_COPILOT_TOKEN_DIR"] = temporary
        with patch.dict(os.environ, environment, clear=True):
            handler = AsyncHTTPHandler()
            await handler.client.aclose()
            handler._client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
            openai_client = AsyncOpenAI(
                api_key="smoke-only-not-a-real-token", base_url="https://api.githubcopilot.com",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
            )
            try:
                for model in ("claude-sonnet-4", "gpt-4.1"):
                    response = await litellm.anthropic.messages.acreate(
                        model=f"github_copilot/{model}", max_tokens=32,
                        system="Preserve this system instruction.",
                        messages=[{"role": "user", "content": "List the files"}],
                        tools=[{"name": "list_files", "description": "List files", "input_schema": {"type": "object", "properties": {}}}],
                        client=handler if model.startswith("claude") else openai_client,
                    )
                    assert response["stop_reason"] == "tool_use", response
                    assert response["content"][0]["type"] == "tool_use", response
                    assert response["content"][0]["name"] == "list_files", response
                    assert response["content"][0]["input"] == {}, response
            finally:
                await handler.client.aclose()
                await openai_client.close()
    assert [path for path, body in observed] == ["/v1/messages", "/chat/completions"], observed
    print("Copilot native Claude and translated GPT tool-call protocol checks passed (mock HTTP, no account).")


if __name__ == "__main__":
    asyncio.run(main())
