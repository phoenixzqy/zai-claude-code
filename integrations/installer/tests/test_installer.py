import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


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


if __name__ == '__main__':
    unittest.main()
