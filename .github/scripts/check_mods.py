"""Run every mod test suite; missing commands and unsupported events fail CI."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    claude = shutil.which('claude')
    if claude is None:
        raise RuntimeError('Install a compatible Claude Code build before validation.')
    failed = False
    with tempfile.TemporaryDirectory(prefix='claude-mod-ci-') as directory:
        environment = dict(os.environ)
        environment.update({
            'CLAUDE_CONFIG_DIR': directory,
            'CLAUDE_CODE_ENABLE_FUNCTION_HOOKS': '1',
            'DISABLE_TELEMETRY': '1',
            'DISABLE_ERROR_REPORTING': '1',
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
        })
        print(subprocess.check_output(
            [claude, '--version'], env=environment, text=True, timeout=30,
        ).strip(), flush=True)
        mods = [path.parent for path in sorted((root / 'mods').glob('*/tests'))]
        if not mods:
            raise RuntimeError('No mod test suites found.')
        for mod in mods:
            print(f'== {mod.name} ==', flush=True)
            result = subprocess.run(
                [claude, 'plugin', 'test', str(mod)], cwd=root,
                env=environment, check=False, timeout=600,
            )
            failed = result.returncode != 0 or failed
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
