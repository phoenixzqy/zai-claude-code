# zai-claude-code

A personal fork for learning and personal use, with a GitHub Copilot gateway for the official Claude Code CLI—not a source build of its proprietary engine.

## Install (Linux/macOS)

Requires Python 3.10+ and Git. Installs the gateway and the official CLI if missing, and permanently adds the launcher to your Bash/Zsh PATH:

```sh
python3 -c 'import pathlib, subprocess, tempfile; temporary = tempfile.TemporaryDirectory(prefix="zai-claude-source-"); source = pathlib.Path(temporary.name) / "source"; subprocess.run(["git", "clone", "--depth", "1", "--branch", "zai-claude-code", "https://github.com/phoenixzqy/zai-claude-code.git", str(source)], check=True); subprocess.run(["python3", str(source / "integrations/installer/install.py")], check=True); temporary.cleanup()'
```

Open a new terminal, then run `zai-claude-code login --tui` (or `login` for command-line login). Copilot usage requires an entitled account.

See [installer details](integrations/installer/README.md) for prerequisites and downloaded-code trust considerations, and the [backup README](README.backup.md) for the full documentation.
