# Source installer (Linux/macOS)

Install our Copilot gateway from `zai-claude-code`, install the official Claude Code CLI if missing, and permanently add `~/.local/bin` to your Bash or Zsh PATH:

```sh
python3 -c 'import pathlib, subprocess, tempfile; temporary = tempfile.TemporaryDirectory(prefix="zai-claude-source-"); source = pathlib.Path(temporary.name) / "source"; subprocess.run(["git", "clone", "--depth", "1", "--branch", "zai-claude-code", "https://github.com/phoenixzqy/zai-claude-code.git", str(source)], check=True); subprocess.run(["python3", str(source / "integrations/installer/install.py")], check=True); temporary.cleanup()'
```

Requires Python 3.10+ with `venv`/pip, Git, Bash, network access, and a Bash or Zsh login shell (`SHELL`). This downloads and executes code from this repository's current customization branch, pinned PyPI gateway dependencies, and (only if needed) `https://claude.ai/install.sh`, which redirects to `downloads.claude.ai`. Review those sources before running. Run as your normal user, not with `sudo`. This is **not** a build of the proprietary Claude Code engine. The privacy PR is not included until merged; this installer does not promise analytics or TUI log-staging suppression. Windows users should follow the gateway's [manual setup](../github-copilot/README.md).

From an existing customization checkout, the equivalent is:

```sh
python3 integrations/installer/install.py
```

Open a new terminal after installation, or run `export PATH="$HOME/.local/bin:$PATH"` in the current one. A child Python process cannot change its parent shell's PATH.

```sh
zai-claude-code login          # command-line device login
zai-claude-code login --tui    # full-screen device login
zai-claude-code models
zai-claude-code run --model MODEL_ID
zai-claude-code logout
```

The `claude` executable is left unchanged. `zai-claude-code` forwards arguments to the [Copilot gateway](../github-copilot/README.md), which requires an entitled account. No login, credential copying, or paid model call happens during installation.

Files installed:

- `~/.local/bin/zai-claude-code`: launcher, refusing to replace an unrelated executable or symlink.
- `~/.local/share/zai-claude-code/`: dedicated Python environment and gateway source snapshot, independent of the temporary clone.
- Bash: append-only PATH blocks in the existing `.bash_profile` or `.bash_login` (otherwise `.profile`) and `.bashrc`.
- Zsh: append-only PATH blocks in `.zprofile` and `.zshrc`, respecting an absolute `ZDOTDIR` when set.

Re-running updates the installed gateway/dependencies without duplicating PATH blocks. Failed installs report nonzero status; a partial dedicated environment may remain for retry. Temporary clones and downloaded official installer scripts are cleaned automatically. For uninstall, remove the launcher and its dedicated share directory, and remove only the `# zai-claude-code PATH` blocks from the listed profiles. Credentials and the official CLI are separate and are not removed. Contributor CI tools/hooks are separate; see [local validation](../../docs/local-validation.md).
