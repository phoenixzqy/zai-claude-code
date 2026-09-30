"""Install the Copilot gateway and official CLI for the current POSIX user."""

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import venv


INSTALL_URL = 'https://claude.ai/install.sh'
LAUNCHER_MARKER = 'ZAI_CLAUDE_CODE_LAUNCHER=1'
PATH_MARKER = '# zai-claude-code PATH'


def shell_profiles(home, environment):
    shell = Path(environment.get('SHELL', '/bin/bash')).name
    if shell == 'zsh':
        directory = Path(environment.get('ZDOTDIR') or home).expanduser()
        if not directory.is_absolute():
            raise ValueError('ZDOTDIR must be absolute.')
        return [directory / '.zprofile', directory / '.zshrc']
    if shell == 'bash':
        login = next((home / name for name in ('.bash_profile', '.bash_login')
                      if (home / name).exists()), home / '.profile')
        return [login, home / '.bashrc']
    raise ValueError('Automatic PATH setup supports Bash and Zsh only.')


def path_block(bin_directory):
    return (
        f'{PATH_MARKER}\n'
        f'case ":$PATH:" in *{shlex.quote(":" + str(bin_directory) + ":")}*) ;;\n'
        f'  *) export PATH={shlex.quote(str(bin_directory))}:"$PATH" ;;\n'
        'esac\n'
    )


def persist_path(profiles, bin_directory):
    block = path_block(bin_directory)
    for profile in profiles:
        previous = profile.read_text() if profile.exists() else ''
        if block in previous:
            continue
        profile.parent.mkdir(parents=True, exist_ok=True)
        with profile.open('a') as output:
            output.write(('\n' if previous and not previous.endswith('\n') else '') + '\n' + block)


def ensure_claude(home):
    existing = shutil.which('claude')
    if existing:
        return Path(existing).absolute()
    local = home / '.local' / 'bin' / 'claude'
    if local.is_file() and os.access(local, os.X_OK):
        return local
    print(f'Installing the official Claude Code CLI from {INSTALL_URL}', flush=True)
    with tempfile.TemporaryDirectory(prefix='zai-claude-official-') as temporary:
        script = Path(temporary) / 'install.sh'
        with urllib.request.urlopen(INSTALL_URL, timeout=60) as response:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != 'https' or final_url.hostname not in ('claude.ai', 'downloads.claude.ai'):
                raise ValueError('Unexpected official installer redirect.')
            script.write_bytes(response.read())
        subprocess.run(['bash', str(script)], check=True, timeout=600)
    if not local.is_file() or not os.access(local, os.X_OK):
        raise RuntimeError(f'Official installer did not create {local}.')
    return local


def launcher_text(python, gateway, claude):
    return (
        '#!/bin/sh\n'
        f'{LAUNCHER_MARKER}\n'
        f'PATH={shlex.quote(str(claude.parent))}:"$PATH"\n'
        'export PATH\n'
        f'exec {shlex.quote(str(python))} {shlex.quote(str(gateway))} "$@"\n'
    )


def install(home, environment, source):
    if sys.version_info < (3, 10):
        raise ValueError('Python 3.10 or newer is required.')
    if sys.platform not in ('linux', 'darwin'):
        raise ValueError('This installer supports Linux and macOS; see manual setup for Windows.')
    profiles = shell_profiles(home, environment)
    bin_directory = home / '.local' / 'bin'
    launcher = bin_directory / 'zai-claude-code'
    if launcher.is_symlink() or (launcher.exists() and LAUNCHER_MARKER not in launcher.read_text().splitlines()):
        raise ValueError(f'Refusing to replace an unrelated executable: {launcher}')
    for profile in profiles:
        if profile.exists() and not os.access(profile, os.W_OK):
            raise ValueError(f'Shell profile is not writable: {profile}')
    claude = ensure_claude(home)
    destination = home / '.local' / 'share' / 'zai-claude-code'
    environment_directory = destination / 'venv'
    python = environment_directory / 'bin' / 'python'
    destination.mkdir(parents=True, exist_ok=True)
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment_directory)
    subprocess.run(
        [str(python), '-m', 'pip', 'install', '-r', str(source / 'requirements.txt')],
        check=True, timeout=1200,
    )
    gateway = destination / 'copilot.py'
    shutil.copyfile(source / 'copilot.py', gateway)
    shutil.copyfile(source / 'requirements.txt', destination / 'requirements.txt')
    bin_directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.zai-claude-code-', dir=bin_directory)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(launcher_text(python, gateway, claude))
        os.chmod(temporary, 0o755)
        os.replace(temporary, launcher)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    persist_path(profiles, bin_directory)
    print(f'Installed {launcher}\nPermanent PATH configured in: ' + ', '.join(map(str, profiles)))
    print('Open a new terminal, then run: zai-claude-code login --tui')
    print(f'In this terminal: export PATH={shlex.quote(str(bin_directory))}:"$PATH"')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        install(Path.home(), os.environ, Path(__file__).resolve().parents[1] / 'github-copilot')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Installation failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
