# zai-claude-code

A personal Claude Code customization for learning and personal use, with privacy defaults and optional GitHub Copilot models. The proprietary CLI engine is still the official Claude Code binary.

## Install (Linux/macOS/Windows)

Requires Python 3.10+ (with pip/venv) and Git. From a checkout of the `zai-claude-code` branch, run:

```sh
python3 scripts/build_and_install_zai_claude_code.py
```

Installs our customized `claude` command, preserving the official CLI and normal interactive/command-line usage, and permanently configures your PATH. On Windows, use `python` or `py -3` instead of `python3`. Open a new terminal and run `claude` as usual. Optional Copilot: `claude copilot login --tui` (or `claude copilot login`), then `claude --model github-copilot/MODEL_ID`; an entitled account is required.

See [installer details](integrations/installer/README.md) for installation without a checkout, prerequisites, and downloaded-code trust considerations, and the [backup README](README.backup.md) for the full documentation.
