# Use GitHub Copilot models with Claude Code

This fork can run Claude Code's conversation TUI using models available to your GitHub Copilot account through a local gateway. Authentication and model selection use explicit commands. Copilot is not an option in Claude's native login menu, and logging in to Copilot does not change what bare `claude` or zai-cli's **Claude Code** app launches.

## Install the customized command

These commands require this fork's installed `claude` launcher, an active GitHub Copilot subscription, and account or organization permission to use the selected model and a third-party client. GitHub CLI authentication (`gh auth login`) and personal access tokens do not replace Copilot device login.

If the launcher is not installed, run this from the fork's repository root:

```sh
python3 scripts/build_and_install_zai_claude_code.py
```

On Windows, use `python` or `py -3` instead of `python3`. The installer preserves the official Claude executable and installs the gateway; it does not build or modify the proprietary engine. Open a new terminal after installation. Restart an already-running zai-cli host if it still resolves a different `claude` executable from its inherited PATH.

## Log in to GitHub Copilot

```sh
claude copilot login
```

Open the GitHub verification URL printed by the command, enter the one-time device code, and approve the authorization. Wait for the command to finish checking your Copilot entitlement and saving credentials. Ctrl-C cancels. You normally log in once; subsequent Copilot launches reuse the saved credentials.

An optional device-login panel is available with `claude copilot login --tui`. Neither login command adds Copilot to the native Claude menus. `claude auth login` and the in-session `/login` command still belong to the official Claude authentication flow.

## List models and start a conversation

```sh
claude copilot models
claude --model github-copilot/MODEL_ID
```

Replace `MODEL_ID` with an exact ID returned by the first command, without the angle brackets or placeholder text. Model availability depends on your account and policies; do not assume a fixed model catalog. The gateway requires a model that advertises tool calling and rejects an unsupported selection before launching Claude.

The `github-copilot/` prefix selects the gateway. A model ID without that prefix does not select Copilot. An equivalent explicit gateway command is:

```sh
claude copilot run --model MODEL_ID
```

Here `MODEL_ID` is the raw ID from the model list, without the `github-copilot/` prefix. For a non-interactive request:

```sh
claude --model github-copilot/MODEL_ID -p "Explain this project"
```

The expected result is a gateway startup message identifying your selected Copilot model, followed by Claude Code's conversation TUI (or the printed response for `-p`). There is no extra startup login or model picker. If the command requests login or reports expired credentials, run `claude copilot login` again and retry.

## Use it inside zai-cli

1. Open a **Terminal** in the zai-cli console.
2. Change to the project directory you want Claude to work in.
3. Run `claude copilot login` if needed, then `claude copilot models`.
4. Run `claude --model github-copilot/MODEL_ID` using a model from that list.

Claude runs inside that terminal using Copilot. Opening the **Claude Code** app from zai-cli's app picker launches the normal native flow; it does not automatically use your saved Copilot credentials or the model you selected in another terminal. This manual terminal launch is not the same as a hosted agent launch with zai-cli's supplied session resources and lifecycle integration. Logging in does not configure zai automation to use Copilot.

## Change models, log out, and troubleshoot

- To change models, exit the conversation and start a new gateway session with another exact model ID. The gateway exposes only the model selected at startup; do not use native `/model` or settings overrides to switch providers during that session. Main, default-tier, and subagent model environment settings point to the selection.
- If `claude` does not recognize the `copilot` command, check which executable your terminal resolves (`command -v claude` in Bash/Zsh, `Get-Command claude` in PowerShell, or `where.exe claude` on Windows). Install this fork's launcher or restart the host after correcting PATH.
- If GitHub declines authorization, the code expires, or entitlement checks fail, retry login and check your subscription and organization policy. An ordinary GitHub login alone is insufficient.
- If the model is unavailable or lacks tool calling, list models again and choose a supported ID. Premium request accounting, quotas, and rate limits still apply.
- To remove the integration's saved local credentials, run `claude copilot logout`. This does not revoke GitHub's OAuth authorization or stop existing conversations; close those sessions and revoke authorization in GitHub settings separately if needed.

Credentials live outside the repository at `~/.config/zai-claude-code/copilot/access-token` and `~/.config/zai-claude-code/copilot/api-key.json`. Never print, commit, or share them.

The gateway listens on `127.0.0.1` with a random per-session authentication key and stops when its Claude child exits. Prompts and repository content are sent to GitHub Copilot. This uses Copilot's device flow and internal APIs, not an officially supported native Anthropic authentication integration. Streaming and tool calls are supported through the gateway, but native feature parity and future API compatibility are not guaranteed. There is no fallback to an independently billed Anthropic account.
