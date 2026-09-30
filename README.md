# zai-claude-code

A personal fork for learning and personal use, with a GitHub Copilot gateway for the official Claude Code CLI—not a source build of its proprietary engine.

## Install (Linux/macOS/Windows)

Requires Python 3.10+ (with pip/venv) and Git. Installs the gateway and the official CLI if missing, and permanently adds the launcher to your Bash/Zsh PATH or Windows user PATH. Run in Bash, Zsh, PowerShell, or Command Prompt:

```sh
python -c "import pathlib, subprocess, sys, tempfile; temporary = tempfile.TemporaryDirectory(prefix='zai-claude-source-'); source = pathlib.Path(temporary.name) / 'source'; clone = ['git', 'clone', '--depth', '1', '--branch', 'zai-claude-code', 'https://github.com/phoenixzqy/zai-claude-code.git', str(source)]; install = [sys.executable, str(source / 'integrations/installer/install.py')]; exec('try:\n subprocess.run(clone, check=True)\n subprocess.run(install, check=True)\nfinally:\n temporary.cleanup()')"
```

If Python 3 is named `python3` or `py -3` on your system, replace only the initial `python`. Open a new terminal, then run `zai-claude-code login --tui` (or `login` for command-line login). Copilot usage requires an entitled account.

See [installer details](integrations/installer/README.md) for prerequisites and downloaded-code trust considerations, and the [backup README](README.backup.md) for the full documentation.
