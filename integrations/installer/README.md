# Source installer (Linux/macOS/Windows)

Install our customized `claude` command from `zai-claude-code`, install the official Claude Code CLI if missing, and prioritize `~/.local/bin` in your Bash/Zsh or Windows user PATH. From the repository root:

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

This downloads and executes code from this repository's current customization branch, pinned PyPI gateway dependencies, and (only if needed) `https://claude.ai/install.sh` or `https://claude.ai/install.ps1`, which redirect to `downloads.claude.ai`. Review those sources before running. Windows uses a process-only PowerShell execution-policy bypass for the official installer, not a persistent policy change. Run as your normal user, not with `sudo` or as Administrator. This is **not** a build of the proprietary Claude Code engine. The installed command applies the canonical privacy opt-outs using the [privacy launcher's](../privacy/README.md) environment handling; internal engine TUI log staging remains unverified.

Open a new terminal after installation. On Linux/macOS, alternatively run `export PATH="$HOME/.local/bin:$PATH"` in the current one. On Windows, restart your terminal application; sign out/in if it retains a stale PATH. A child Python process cannot change its parent shell's PATH.

```sh
claude
claude --resume
claude -p "Your prompt"
claude copilot login
claude copilot login --tui
claude copilot models
claude --model github-copilot/MODEL_ID
claude copilot logout
```

Bare `claude` in an interactive terminal now opens a launcher-owned **Select login method** TUI with **GitHub Copilot account** alongside the native Claude/Anthropic/third-party flow. Use Up/Down and Enter (or a number then Enter); Esc or Ctrl-C cancels. Selecting Copilot shows its device-login TUI if needed, then a picker of your account's tool-calling models, and launches the real Claude UI through the private gateway. Existing Copilot credentials are reused; `claude auth login` in a terminal opens the same provider picker and forces fresh login without launching a conversation.

Selecting the native option preserves the official CLI's own onboarding and authentication. Native flags/subcommands (including `--resume`, `--continue`, `-p`, and explicit models) and non-interactive invocations bypass the startup picker, inheriting your working directory, terminal, and authentication. `--settings` JSON or files remain supported; fork privacy settings take precedence. The `copilot` namespace and `github-copilot/` model prefix remain available for explicit/scripted use. The picker belongs to the launcher: it does not modify the proprietary engine's in-session `/login` or `/model` menus. No login, credential copying, or paid model call happens during installation.

The engine's early `plugin test` entry point requires its original argument prefix; it is forwarded without added settings flags, while still applying the privacy environment. Custom settings are merged into a private, temporary settings file rather than exposing their contents in process arguments; that file is removed when the child exits. No terminal output is staged.

The native executable is preserved at its resolved original path. If it is a regular file at the public launcher path, a copy is saved under the dedicated `native/` directory before replacement. The saved absolute path prevents recursion on reinstall. An installer-owned old `zai-claude-code` launcher is removed; unrelated files are never removed. If an official updater overwrites the wrapper, rerun this installer.

Files installed:

- `~/.local/bin/claude` (Windows: `claude.exe`): customized launcher. An existing CLI at this path is preserved before replacement; conflicting unrelated files and dangling symlinks are rejected. Windows uses pip's bundled distlib executable launcher, not a batch script.
- `~/.local/share/zai-claude-code/`: dedicated Python environment, launcher/gateway/privacy source snapshots, canonical privacy settings snapshot, and `runtime.json` holding the native CLI path, independent of the temporary clone.
- Bash: append-only PATH blocks in the existing `.bash_profile` or `.bash_login` (otherwise `.profile`) and `.bashrc`.
- Zsh: append-only PATH blocks in `.zprofile` and `.zshrc`, respecting an absolute `ZDOTDIR` when set.
- Windows: prioritize the directory in `HKEY_CURRENT_USER\Environment\Path`, preserving other entries and registry value type; system PATH is untouched. A system-wide `claude` earlier in system PATH may still take precedence: check `where.exe claude`. The dedicated environment uses `venv\Scripts\python.exe`.

Re-running updates the customization/dependencies without duplicating PATH blocks. Failed installs report nonzero status; a partial dedicated environment may remain for retry. Temporary clones, launcher staging, and downloaded official installer scripts are cleaned automatically, including on failure. For uninstall, first restore any `native/claude` backup to the public launcher path (otherwise remove only the wrapper), then remove its dedicated share directory and the `# zai-claude-code PATH` blocks (Windows: remove only the added directory from your user PATH). Keep credentials and the external official CLI. Contributor CI tools/hooks are separate; see [local validation](../../docs/local-validation.md).
