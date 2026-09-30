"""Install the Copilot gateway and official CLI for the current user."""

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
WINDOWS_INSTALL_URL = 'https://claude.ai/install.ps1'
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


def notify_windows_environment():
    import ctypes
    from ctypes import wintypes

    broadcast = ctypes.windll.user32.SendMessageTimeoutW
    broadcast.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                          wintypes.LPCWSTR, wintypes.UINT, wintypes.UINT,
                          ctypes.POINTER(ctypes.c_size_t)]
    broadcast.restype = wintypes.LPARAM
    result = ctypes.c_size_t()
    if not broadcast(0xffff, 0x001a, 0, 'Environment', 2, 5000, ctypes.byref(result)):
        print('PATH saved; sign out and back in if new terminals still use the old PATH.')


def persist_windows_path(bin_directory):
    import ntpath
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, 'Environment', 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        try:
            previous, value_type = winreg.QueryValueEx(key, 'Path')
        except FileNotFoundError:
            previous, value_type = '', winreg.REG_EXPAND_SZ
        if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(previous, str):
            raise ValueError('User PATH is not a string registry value.')
        directory = str(bin_directory)
        if ';' in directory:
            raise ValueError('The installation directory must not contain a semicolon.')
        normalized = ntpath.normcase(ntpath.normpath(directory))
        entries = (ntpath.normcase(ntpath.normpath(os.path.expandvars(entry.strip().strip('"'))))
                   for entry in previous.split(';') if entry.strip())
        if normalized not in entries:
            updated = previous + (';' if previous and not previous.endswith(';') else '') + directory
            winreg.SetValueEx(key, 'Path', 0, value_type, updated)
    notify_windows_environment()


def ensure_claude(home):
    windows = sys.platform == 'win32'
    existing = shutil.which('claude.exe' if windows else 'claude')
    if existing:
        return Path(existing).absolute()
    local = home / '.local' / 'bin' / ('claude.exe' if windows else 'claude')
    if local.is_file() and os.access(local, os.X_OK):
        return local
    url = WINDOWS_INSTALL_URL if windows else INSTALL_URL
    print(f'Installing the official Claude Code CLI from {url}', flush=True)
    with tempfile.TemporaryDirectory(prefix='zai-claude-official-') as temporary:
        script = Path(temporary) / ('install.ps1' if windows else 'install.sh')
        with urllib.request.urlopen(url, timeout=60) as response:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != 'https' or final_url.hostname not in ('claude.ai', 'downloads.claude.ai'):
                raise ValueError('Unexpected official installer redirect.')
            script.write_bytes(response.read())
        command = (['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                    'Bypass', '-File', str(script)] if windows else ['bash', str(script)])
        subprocess.run(command, check=True, timeout=600)
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


def windows_launcher(python, gateway, claude):
    template = (
        f'{LAUNCHER_MARKER}\n'
        'import os, runpy\n'
        f"os.environ['PATH'] = {str(claude.parent)!r} + os.pathsep + os.environ.get('PATH', '')\n"
        f"runpy.run_path({str(gateway)!r}, run_name='__main__')\n"
    )
    generator = (
        'import sys; from pip._vendor.distlib.scripts import ScriptMaker; '
        'maker = ScriptMaker(None, sys.argv[1]); maker.variants = {\'\'}; '
        "maker.script_template = sys.argv[2].replace('%', '%%'); "
        "maker.make('zai-claude-code = copilot:main')"
    )
    with tempfile.TemporaryDirectory(prefix='zai-claude-launcher-') as temporary:
        subprocess.run([str(python), '-c', generator, temporary, template], check=True, timeout=60)
        return (Path(temporary) / 'zai-claude-code.exe').read_bytes()


def ensure_environment(directory, windows):
    bin_directory = directory / ('Scripts' if windows else 'bin')
    python = bin_directory / ('python.exe' if windows else 'python')
    if directory.is_symlink() or bin_directory.is_symlink():
        raise ValueError('Refusing to modify a symbolic-linked environment directory.')
    if python.exists():
        health = subprocess.run([str(python), '-I', '-c', 'import pip'],
                                capture_output=True, text=True, check=False, timeout=30)
        if health.returncode == 0:
            return python
        print('Repairing the incomplete Python environment.', flush=True)
    if not windows:
        names = {'python', 'python3', f'python3.{sys.version_info.minor}',
                 Path(sys._base_executable).name}
        executables = [bin_directory / name for name in names
                       if (bin_directory / name).exists() or (bin_directory / name).is_symlink()]
        configuration = directory / 'pyvenv.cfg'
        if executables and (not configuration.is_file() or configuration.is_symlink()):
            raise ValueError('Refusing to repair a directory without a regular pyvenv.cfg.')
        for executable in executables:
            executable.unlink()
    try:
        venv.EnvBuilder(with_pip=True, symlinks=not windows).create(directory)
    except subprocess.CalledProcessError as error:
        output = error.output or b''
        if isinstance(output, bytes):
            output = output.decode(errors='replace')
        raise RuntimeError(f'Python environment bootstrap failed:\n{output.strip()}\n'
                           'Use a Python installation with working venv/ensurepip support.') from error
    return python


def install(home, environment, source):
    if sys.version_info < (3, 10):
        raise ValueError('Python 3.10 or newer is required.')
    if sys.platform not in ('linux', 'darwin', 'win32'):
        raise ValueError('This installer supports Linux, macOS, and Windows.')
    windows = sys.platform == 'win32'
    profiles = [] if windows else shell_profiles(home, environment)
    bin_directory = home / '.local' / 'bin'
    if windows and ';' in str(bin_directory):
        raise ValueError('The installation directory must not contain a semicolon.')
    launcher = bin_directory / ('zai-claude-code.exe' if windows else 'zai-claude-code')
    owned = (launcher.exists() and
             (LAUNCHER_MARKER.encode() in launcher.read_bytes() if windows
              else LAUNCHER_MARKER in launcher.read_text().splitlines()))
    if launcher.is_symlink() or (launcher.exists() and not owned):
        raise ValueError(f'Refusing to replace an unrelated executable: {launcher}')
    for profile in profiles:
        if profile.exists() and not os.access(profile, os.W_OK):
            raise ValueError(f'Shell profile is not writable: {profile}')
    claude = ensure_claude(home)
    destination = home / '.local' / 'share' / 'zai-claude-code'
    environment_directory = destination / 'venv'
    destination.mkdir(parents=True, exist_ok=True)
    python = ensure_environment(environment_directory, windows)
    subprocess.run(
        [str(python), '-m', 'pip', 'install', '-r', str(source / 'requirements.txt')],
        check=True, timeout=1200,
    )
    gateway = destination / 'copilot.py'
    shutil.copyfile(source / 'copilot.py', gateway)
    shutil.copyfile(source / 'requirements.txt', destination / 'requirements.txt')
    content = windows_launcher(python, gateway, claude) if windows else launcher_text(python, gateway, claude).encode()
    bin_directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.zai-claude-code-', dir=bin_directory)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
        os.chmod(temporary, 0o755)
        os.replace(temporary, launcher)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if windows:
        persist_windows_path(bin_directory)
    else:
        persist_path(profiles, bin_directory)
    location = r'HKCU\Environment\Path' if windows else ', '.join(map(str, profiles))
    print(f'Installed {launcher}\nPermanent PATH configured in: {location}')
    print('Open a new terminal, then run: zai-claude-code login --tui')
    if not windows:
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
