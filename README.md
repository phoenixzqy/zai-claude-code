# zai-claude-code

A personal fork for learning and personal use, with a GitHub Copilot gateway for the official Claude Code CLI—not a source build of its proprietary engine.

## Install (Linux/macOS/Windows)

Requires Python 3.10+ (with pip/venv) and Git. From a checkout of the `zai-claude-code` branch, run:

```sh
python3 scripts/build_and_install_zai_claude_code.py
```

Installs the gateway and the official CLI if missing, and permanently adds the launcher to your Bash/Zsh PATH or Windows user PATH. On Windows, use `python` or `py -3` instead of `python3`. Open a new terminal, then run `zai-claude-code login --tui` (or `login` for command-line login). Copilot usage requires an entitled account.

See [installer details](integrations/installer/README.md) for installation without a checkout, prerequisites, and downloaded-code trust considerations, and the [backup README](README.backup.md) for the full documentation.
