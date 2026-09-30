# Source installer (Linux/macOS/Windows)

Install our Copilot gateway from `zai-claude-code`, install the official Claude Code CLI if missing, and permanently add `~/.local/bin` to your Bash/Zsh or Windows user PATH. From the repository root:

```sh
python3 scripts/build_and_install_zai_claude_code.py
```

On Windows, use `python` or `py -3` instead of `python3`. The script delegates to the existing cross-platform installer, keeping one source of truth; it does not build the proprietary CLI engine.

Linux/macOS environments use symlinks so uv-managed Python retains its standard-library location. Re-running repairs an incomplete environment (including a missing pip) without removing other installed files. Windows keeps the standard copy-based environment. If bootstrapping still fails, the installer displays the underlying ensurepip output; ensure your Python distribution includes working `venv`/`ensurepip` support (Debian/Ubuntu system Python may require `python3-venv`).

Without a checkout, this command clones the customization branch temporarily and runs the same script in Bash, Zsh, PowerShell, or Command Prompt:

```sh
python -c "import pathlib, subprocess, sys, tempfile; temporary = tempfile.TemporaryDirectory(prefix='zai-claude-source-'); source = pathlib.Path(temporary.name) / 'source'; clone = ['git', 'clone', '--depth', '1', '--branch', 'zai-claude-code', 'https://github.com/phoenixzqy/zai-claude-code.git', str(source)]; install = [sys.executable, str(source / 'scripts/build_and_install_zai_claude_code.py')]; exec('try:\n subprocess.run(clone, check=True)\n subprocess.run(install, check=True)\nfinally:\n temporary.cleanup()')"
```

Requires Python 3.10+ with `venv`/pip, Git, and network access. Replace only the initial `python` with `python3` or `py -3` if needed; the child installer uses the same interpreter. Linux/macOS require Bash and a Bash or Zsh login shell (`SHELL`). Native Windows requires Windows PowerShell and Git for Windows (including Git Bash for the official CLI); WSL uses the Linux path. Other operating systems/shells are not supported by automatic setup.

This downloads and executes code from this repository's current customization branch, pinned PyPI gateway dependencies, and (only if needed) `https://claude.ai/install.sh` or `https://claude.ai/install.ps1`, which redirect to `downloads.claude.ai`. Review those sources before running. Windows uses a process-only PowerShell execution-policy bypass for the official installer, not a persistent policy change. Run as your normal user, not with `sudo` or as Administrator. This is **not** a build of the proprietary Claude Code engine. The [privacy launcher](../privacy/README.md) is separate and is not activated by this installer; this installer does not promise analytics or TUI log-staging suppression.

Open a new terminal after installation. On Linux/macOS, alternatively run `export PATH="$HOME/.local/bin:$PATH"` in the current one. On Windows, restart your terminal application; sign out/in if it retains a stale PATH. A child Python process cannot change its parent shell's PATH.

```sh
zai-claude-code login          # command-line device login
zai-claude-code login --tui    # full-screen device login
zai-claude-code models
zai-claude-code run --model MODEL_ID
zai-claude-code logout
```

The `claude` executable is left unchanged. `zai-claude-code` forwards arguments to the [Copilot gateway](../github-copilot/README.md), which requires an entitled account. No login, credential copying, or paid model call happens during installation.

Files installed:

- `~/.local/bin/zai-claude-code` (Windows: `zai-claude-code.exe`): launcher, refusing to replace an unrelated executable or symlink. Windows uses pip's bundled distlib native executable launcher, not a batch script, so arguments do not pass through a command shell.
- `~/.local/share/zai-claude-code/`: dedicated Python environment and gateway source snapshot, independent of the temporary clone.
- Bash: append-only PATH blocks in the existing `.bash_profile` or `.bash_login` (otherwise `.profile`) and `.bashrc`.
- Zsh: append-only PATH blocks in `.zprofile` and `.zshrc`, respecting an absolute `ZDOTDIR` when set.
- Windows: append only to `HKEY_CURRENT_USER\Environment\Path`, preserving existing entries and registry value type; system PATH is untouched. The dedicated environment uses `venv\Scripts\python.exe`.

Re-running updates the installed gateway/dependencies without duplicating PATH entries. Failed installs report nonzero status; a partial dedicated environment may remain for retry. Temporary clones, launcher staging, and downloaded official installer scripts are cleaned automatically, including on failure. For uninstall, remove the launcher and its dedicated share directory, and remove only the `# zai-claude-code PATH` blocks from the listed profiles (Windows: remove only the added directory from your user PATH). Credentials and the official CLI are separate and are not removed. Contributor CI tools/hooks are separate; see [local validation](../../docs/local-validation.md).
