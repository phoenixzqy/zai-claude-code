# GitHub Copilot for Claude Code

An opt-in local gateway that logs in to GitHub Copilot and lets the installed Claude Code CLI use a model available to your Copilot account. It uses LiteLLM's maintained `github_copilot` provider and Anthropic Messages endpoint: Claude models use Copilot's native Messages API; other models use LiteLLM's protocol translation, including streaming and tool calls.

This is not a modification to Claude Code's native `/login` or model picker. The CLI engine source is not in this repository. Both login modes below belong to this integration, and the gateway is active only for the Claude Code process it launches. No global Claude settings or existing login credentials are changed.

## Requirements

- Python 3.10+ and an installed `claude` executable.
- An active GitHub Copilot subscription, access to the selected model, and organization policies permitting its use. An ordinary `gh auth login` session or GitHub personal access token is not a Copilot login.
- Permission to use a third-party client with your account. This integration uses Copilot's device flow and internal APIs, not an officially supported GitHub or Anthropic authentication integration. Those APIs, model availability, and policy requirements may change; no bypass of entitlement, rate limits, premium-request accounting, or organization restrictions is provided.

From the repository root, install the pinned gateway dependency into a dedicated environment:

```sh
python3 -m venv ~/.venvs/zai-claude-copilot
~/.venvs/zai-claude-copilot/bin/python -m pip install -r integrations/github-copilot/requirements.txt
```

On Windows, use the environment's `Scripts/python.exe` instead of `bin/python`.

## Command-line login

```sh
~/.venvs/zai-claude-copilot/bin/python integrations/github-copilot/copilot.py login
```

The command displays a GitHub URL and a one-time device code. Open the URL in your browser, enter the code, and approve the GitHub authorization. The command waits for approval and checks your Copilot entitlement before saving credentials. Ctrl-C cancels login. Expired or declined codes fail clearly; `slow_down` responses increase the polling interval.

## TUI login

```sh
~/.venvs/zai-claude-copilot/bin/python integrations/github-copilot/copilot.py login --tui
```

An interactive terminal shows a full-screen login panel with the verification URL, device code, and remaining time. Approve the same browser device flow; Ctrl-C cancels and restores the terminal. In non-interactive terminals use the plain command-line mode instead. Both modes use the same authorization and credential storage.

## Choose a model and run Claude Code

```sh
~/.venvs/zai-claude-copilot/bin/python integrations/github-copilot/copilot.py models
~/.venvs/zai-claude-copilot/bin/python integrations/github-copilot/copilot.py run --model MODEL_ID
~/.venvs/zai-claude-copilot/bin/python integrations/github-copilot/copilot.py run --model MODEL_ID -- -p 'Explain this project'
```

Replace `MODEL_ID` with an exact ID returned by `models`; no hardcoded model catalog is assumed. The model must advertise tool calling. The launcher routes the main, default tier, and subagent models to that selection so helper calls do not silently go to Anthropic. Do not use `--model`, `--settings`, `/model`, or other Claude configuration overrides to select a different provider within this session: the gateway exposes only the selected model. Start a new launcher session to change models.

The launcher starts a gateway on a dynamically selected `127.0.0.1` port, protects it with a random per-session bearer key, and configures only the child Claude process. It waits for authenticated readiness and stops its own gateway and removes its temporary configuration when the child exits, startup fails, or you cancel. Prompts and repository content are sent to GitHub Copilot, not an Anthropic API account; review GitHub's data policies before use. Gateway output and payload logging are disabled. Unsupported Claude features or provider parameters may fail; there is no fallback to an independently billed Anthropic account. Remote-control, cloud sessions, server-executed Anthropic tools, and arbitrary model switching are not supported by this gateway.

## Credentials and logout

Credentials are stored outside the checkout at `~/.config/zai-claude-code/copilot/access-token` and `~/.config/zai-claude-code/copilot/api-key.json`. The directory has mode `0700` and files have mode `0600` on POSIX systems. On Windows, protect the directory with your account's filesystem ACLs. Never commit these files, include them in logs, or share them. `--state-dir PATH` before the subcommand selects a separate credential directory.

```sh
~/.venvs/zai-claude-copilot/bin/python integrations/github-copilot/copilot.py logout
```

Logout deletes only this integration's two local token files. It does not revoke GitHub authorization or stop already running sessions; quit those sessions and revoke the OAuth authorization through GitHub settings if necessary. Copilot's short-lived token is refreshed by the provider while running. If GitHub revokes the underlying authorization, quit the session and log in again.

## Validation

```sh
python3 -B -m unittest discover -s integrations/github-copilot/tests -v
~/.venvs/zai-claude-copilot/bin/python -B integrations/github-copilot/tests/proxy_smoke.py
~/.venvs/zai-claude-copilot/bin/python -B integrations/github-copilot/tests/protocol_smoke.py
```

Automated tests do not use a real GitHub account or incur model charges. The gateway smoke test uses isolated dummy credentials and a mock model to check authentication, JSON, and SSE responses. The protocol smoke test intercepts upstream HTTP requests to check native Claude and translated GPT tool calls, including system instructions and bearer headers. Full account validation still requires a person to approve device login in both modes and exercise a tool-calling and streaming conversation using an entitled model.
