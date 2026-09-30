import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@unittest.skipUnless(os.name == 'posix', 'Installer and shell setup require a POSIX platform')
class InstallerTests(unittest.TestCase):
    def test_bash_preserves_existing_login_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.bash_login').touch()
            self.assertEqual(installer.shell_profiles(home, {'SHELL': '/bin/bash'}),
                             [home / '.bash_login', home / '.bashrc'])

    def test_zsh_honors_zdotdir(self):
        self.assertEqual(installer.shell_profiles(Path('/home/user'),
                         {'SHELL': '/bin/zsh', 'ZDOTDIR': '/home/user/custom'}),
                         [Path('/home/user/custom/.zprofile'), Path('/home/user/custom/.zshrc')])

    def test_unsupported_shell_fails_before_installing(self):
        with patch.object(installer, 'ensure_claude') as ensure:
            with self.assertRaisesRegex(ValueError, 'Bash and Zsh'):
                installer.install(Path('/unused'), {'SHELL': '/bin/fish'}, Path('/unused'))
            ensure.assert_not_called()

    def test_path_update_is_additive_idempotent_and_shell_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            profile = home / '.profile'
            profile.write_text('export KEEP_SETTING=yes')
            bin_directory = home / "directory with 'quotes' and $variables"
            installer.persist_path([profile], bin_directory)
            first = profile.read_text()
            installer.persist_path([profile], bin_directory)
            self.assertEqual(first, profile.read_text())
            result = subprocess.check_output(
                ['bash', '-c', 'source "$1"; source "$1"; printf "%s\\n%s" "$PATH" "$KEEP_SETTING"',
                 'test', str(profile)], env={'PATH': '/usr/bin:/bin'}, text=True,
            )
            self.assertEqual(result, f'{bin_directory}:/usr/bin:/bin\nyes')

    def test_launcher_preserves_arguments_and_finds_official_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'spaces and quotes\' here'
            root.mkdir()
            python = root / 'python'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$PATH" "$@"\n')
            python.chmod(0o755)
            gateway = root / 'copilot.py'
            claude = root / 'official' / 'claude'
            launcher = root / 'launcher'
            launcher.write_text(installer.launcher_text(python, gateway, claude))
            result = subprocess.check_output(['sh', str(launcher), 'login', '--tui', 'space arg'],
                                             env={'PATH': '/usr/bin:/bin'}, text=True)
            self.assertEqual(result.splitlines(),
                             [f'{claude.parent}:/usr/bin:/bin', str(gateway), 'login', '--tui', 'space arg'])

    def test_existing_claude_needs_no_download(self):
        with patch.object(installer.shutil, 'which', return_value='/official/claude'), \
                patch.object(installer.urllib.request, 'urlopen') as download:
            self.assertEqual(installer.ensure_claude(Path('/home/user')), Path('/official/claude'))
            download.assert_not_called()

    def test_official_install_cleans_download_and_checks_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            local = home / '.local/bin/claude'
            downloaded = []
            def run_install(command, **kwargs):
                downloaded.append(Path(command[1]))
                self.assertEqual(downloaded[-1].read_text(), 'official installer')
                local.parent.mkdir(parents=True)
                local.write_text('official CLI')
                local.chmod(0o755)
            with patch.object(installer.shutil, 'which', return_value=None), \
                    patch.object(installer.urllib.request, 'urlopen') as download, \
                    patch.object(installer.subprocess, 'run', side_effect=run_install):
                response = download.return_value.__enter__.return_value
                response.geturl.return_value = 'https://downloads.claude.ai/claude-code-releases/bootstrap.sh'
                response.read.return_value = b'official installer'
                self.assertEqual(installer.ensure_claude(home), local)
            self.assertFalse(downloaded[0].exists())
            self.assertFalse(downloaded[0].parent.exists())

    def test_official_download_redirect_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(installer.shutil, 'which', return_value=None), \
                    patch.object(installer.urllib.request, 'urlopen') as download, \
                    patch.object(installer.subprocess, 'run') as run:
                response = download.return_value.__enter__.return_value
                response.geturl.return_value = 'https://example.com/installer'
                with self.assertRaisesRegex(ValueError, 'redirect'):
                    installer.ensure_claude(Path(temporary))
                run.assert_not_called()

    def test_full_install_and_repeat_preserve_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            home.mkdir()
            source = Path(temporary) / 'source'
            source.mkdir()
            (source / 'copilot.py').write_text('print("gateway")\n')
            (source / 'requirements.txt').write_text('dependency==1\n')
            python = home / '.local/share/zai-claude-code/venv/bin/python'
            def create_environment(directory):
                python.parent.mkdir(parents=True)
                python.touch()
            with patch.object(installer, 'ensure_claude', return_value=Path('/official/claude')), \
                    patch.object(installer.venv.EnvBuilder, 'create', side_effect=create_environment) as create, \
                    patch.object(installer.subprocess, 'run') as run:
                installer.install(home, {'SHELL': '/bin/bash'}, source)
                first = (home / '.profile').read_text()
                installer.install(home, {'SHELL': '/bin/bash'}, source)
                create.assert_called_once()
                self.assertEqual(run.call_count, 2)
                self.assertEqual(first, (home / '.profile').read_text())
            launcher = home / '.local/bin/zai-claude-code'
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertEqual((home / '.local/share/zai-claude-code/copilot.py').read_text(),
                             (source / 'copilot.py').read_text())
            self.assertEqual(list(launcher.parent.glob('.zai-claude-code-*')), [])

    def test_refuses_unrelated_launcher_or_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            launcher = home / '.local/bin/zai-claude-code'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('unrelated')
            with patch.object(installer, 'ensure_claude') as ensure:
                with self.assertRaisesRegex(ValueError, 'unrelated executable'):
                    installer.install(home, {'SHELL': '/bin/bash'}, Path('/source'))
                launcher.unlink()
                launcher.symlink_to(home / 'missing')
                with self.assertRaisesRegex(ValueError, 'unrelated executable'):
                    installer.install(home, {'SHELL': '/bin/bash'}, Path('/source'))
                ensure.assert_not_called()

    def test_dependency_failure_does_not_publish_launcher_or_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            python = home / '.local/share/zai-claude-code/venv/bin/python'
            python.parent.mkdir(parents=True)
            python.touch()
            with patch.object(installer, 'ensure_claude', return_value=Path('/official/claude')), \
                    patch.object(installer.subprocess, 'run',
                                 side_effect=subprocess.CalledProcessError(1, 'pip')):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install(home, {'SHELL': '/bin/bash'}, Path('/source'))
            self.assertFalse((home / '.local/bin/zai-claude-code').exists())
            self.assertFalse((home / '.profile').exists())


class CrossPlatformInstallerTests(unittest.TestCase):
    def registry(self, previous='', value_type=2):
        registry = MagicMock(REG_SZ=1, REG_EXPAND_SZ=2, KEY_QUERY_VALUE=1, KEY_SET_VALUE=2)
        registry.QueryValueEx.return_value = previous, value_type
        return registry

    def test_windows_path_preserves_registry_type_and_entries(self):
        for value_type in (1, 2):
            registry = self.registry(r'%TOOLS%\bin;C:\Existing', value_type)
            with patch.dict(sys.modules, winreg=registry), \
                    patch.object(installer, 'notify_windows_environment') as notify:
                installer.persist_windows_path(Path('C:/User/bin'))
            registry.SetValueEx.assert_called_once_with(
                registry.CreateKeyEx.return_value.__enter__.return_value, 'Path', 0,
                value_type, r'%TOOLS%\bin;C:\Existing;' + str(Path('C:/User/bin')))
            notify.assert_called_once()

    def test_windows_path_is_case_insensitive_and_idempotent(self):
        registry = self.registry(r'C:\Existing;"c:\USER\BIN\";')
        with patch.dict(sys.modules, winreg=registry), \
                patch.object(installer, 'notify_windows_environment'):
            installer.persist_windows_path(Path('C:/User/bin'))
        registry.SetValueEx.assert_not_called()

    def test_missing_windows_user_path_is_created(self):
        registry = self.registry()
        registry.QueryValueEx.side_effect = FileNotFoundError
        with patch.dict(sys.modules, winreg=registry), \
                patch.object(installer, 'notify_windows_environment'):
            installer.persist_windows_path(Path('C:/User/bin'))
        self.assertEqual(registry.SetValueEx.call_args.args[3:], (2, str(Path('C:/User/bin'))))

    def test_invalid_windows_path_is_not_overwritten(self):
        registry = self.registry(123, 4)
        with patch.dict(sys.modules, winreg=registry):
            with self.assertRaisesRegex(ValueError, 'not a string'):
                installer.persist_windows_path(Path('C:/User/bin'))
        registry.SetValueEx.assert_not_called()

    def test_windows_official_installer_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            local = home / '.local/bin/claude.exe'
            scripts = []
            def run_install(command, **kwargs):
                self.assertEqual(command[:6], ['powershell.exe', '-NoProfile', '-NonInteractive',
                                               '-ExecutionPolicy', 'Bypass', '-File'])
                script = Path(command[-1])
                scripts.append(script)
                self.assertEqual(script.suffix, '.ps1')
                local.parent.mkdir(parents=True)
                local.write_bytes(b'official CLI')
                local.chmod(0o755)
            with patch.object(installer.sys, 'platform', 'win32'), \
                    patch.object(installer.shutil, 'which', return_value=None) as which, \
                    patch.object(installer.urllib.request, 'urlopen') as download, \
                    patch.object(installer.subprocess, 'run', side_effect=run_install):
                response = download.return_value.__enter__.return_value
                response.geturl.return_value = 'https://downloads.claude.ai/claude-code-releases/bootstrap.ps1'
                response.read.return_value = b'official installer'
                self.assertEqual(installer.ensure_claude(home), local)
                which.assert_called_once_with('claude.exe')
                download.assert_called_once_with(installer.WINDOWS_INSTALL_URL, timeout=60)
            self.assertFalse(scripts[0].parent.exists())

    def test_windows_launcher_staging_cleanup_and_safe_template(self):
        stages = []
        gateway = Path("C:/User's files/%name%/copilot.py")
        def generate(command, **kwargs):
            stages.append(Path(command[3]))
            with patch('runpy.run_path') as run_gateway, patch.dict(os.environ, PATH='existing'):
                exec(command[4], {})
                run_gateway.assert_called_once_with(str(gateway), run_name='__main__')
                self.assertEqual(os.environ['PATH'], str(Path('C:/Official')) + os.pathsep + 'existing')
            (stages[-1] / 'zai-claude-code.exe').write_bytes(b'native launcher')
        with patch.object(installer.subprocess, 'run', side_effect=generate):
            self.assertEqual(installer.windows_launcher(Path('python.exe'), gateway,
                             Path('C:/Official/claude.exe')), b'native launcher')
        self.assertFalse(stages[0].exists())

    def test_windows_launcher_failure_cleans_staging(self):
        stages = []
        def fail(command, **kwargs):
            stages.append(Path(command[3]))
            raise subprocess.CalledProcessError(1, command)
        with patch.object(installer.subprocess, 'run', side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.windows_launcher(Path('python.exe'), Path('copilot.py'), Path('claude.exe'))
        self.assertFalse(stages[0].exists())

    def test_windows_semicolon_directory_fails_before_installing(self):
        with patch.object(installer.sys, 'platform', 'win32'), \
                patch.object(installer, 'ensure_claude') as ensure:
            with self.assertRaisesRegex(ValueError, 'semicolon'):
                installer.install(Path('C:/User;name'), {}, Path('source'))
            ensure.assert_not_called()

    def test_windows_full_install_and_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            source = Path(temporary) / 'source'
            source.mkdir()
            (source / 'copilot.py').write_text('print("gateway")\n')
            (source / 'requirements.txt').write_text('dependency==1\n')
            python = home / '.local/share/zai-claude-code/venv/Scripts/python.exe'
            def create_environment(directory):
                python.parent.mkdir(parents=True)
                python.touch()
            with patch.object(installer.sys, 'platform', 'win32'), \
                    patch.object(installer, 'ensure_claude', return_value=Path('C:/Official/claude.exe')), \
                    patch.object(installer.venv.EnvBuilder, 'create', side_effect=create_environment) as create, \
                    patch.object(installer.subprocess, 'run') as run, \
                    patch.object(installer, 'windows_launcher', return_value=installer.LAUNCHER_MARKER.encode()), \
                    patch.object(installer, 'persist_windows_path') as persist:
                installer.install(home, {}, source)
                installer.install(home, {}, source)
                create.assert_called_once()
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args.args[0][0], str(python))
                self.assertEqual(persist.call_count, 2)
            self.assertTrue((home / '.local/bin/zai-claude-code.exe').exists())
            self.assertFalse((home / '.profile').exists())
            self.assertEqual(list((home / '.local/bin').glob('.zai-claude-code-*')), [])

    def test_windows_refuses_unrelated_executable_before_installing(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            launcher = home / '.local/bin/zai-claude-code.exe'
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b'unrelated executable')
            with patch.object(installer.sys, 'platform', 'win32'), \
                    patch.object(installer, 'ensure_claude') as ensure:
                with self.assertRaisesRegex(ValueError, 'unrelated executable'):
                    installer.install(home, {}, Path('/source'))
                ensure.assert_not_called()

    def test_readme_one_liner_uses_same_interpreter_and_cleans_on_failure(self):
        readme = Path(__file__).resolve().parents[3] / 'README.md'
        command = next(line for line in readme.read_text().splitlines() if line.startswith('python -c '))
        detailed = Path(__file__).resolve().parents[1] / 'README.md'
        self.assertIn(command, detailed.read_text())
        arguments = shlex.split(command)
        for fail_at in (None, 0, 1):
            calls = []
            directories = []
            def run(command, **kwargs):
                calls.append(command)
                if command[0] == 'git':
                    directories.append(Path(command[-1]).parent)
                    self.assertTrue(directories[-1].exists())
                else:
                    self.assertEqual(command[0], sys.executable)
                if len(calls) - 1 == fail_at:
                    raise subprocess.CalledProcessError(1, command)
            with patch.object(subprocess, 'run', side_effect=run):
                if fail_at is None:
                    exec(arguments[2], {})
                    self.assertEqual(len(calls), 2)
                else:
                    with self.assertRaises(subprocess.CalledProcessError):
                        exec(arguments[2], {})
            self.assertFalse(directories[0].exists())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows executable validation requires Windows')
    def test_native_windows_launcher_preserves_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "spaces and 'quotes' %percent%"
            root.mkdir()
            gateway = root / 'copilot.py'
            gateway.write_text('import sys; print(repr(sys.argv[1:]))\n')
            launcher = root / 'zai-claude-code.exe'
            launcher.write_bytes(installer.windows_launcher(Path(sys.executable), gateway,
                                                           root / 'official/claude.exe'))
            arguments = ['login', '--tui', 'space arg', 'quote"arg', '&echo unsafe', '%PATH%']
            result = subprocess.check_output([str(launcher), *arguments], text=True)
            self.assertEqual(result.strip(), repr(arguments))
            self.assertIn(installer.LAUNCHER_MARKER.encode(), launcher.read_bytes())


if __name__ == '__main__':
    unittest.main()
