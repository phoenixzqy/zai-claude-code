"""Run every enabled mod test; report the user-approved compatibility quarantine."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DISABLED_REGISTER = 'mods/sec-default/tests/register.disabled.ts'


def main():
    root = ROOT
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
        if (root / DISABLED_REGISTER).is_file():
            print(
                f'DISABLED (not a pass): {DISABLED_REGISTER} — registration tests require '
                'prompt.compose, rejected by Claude Code 2.1.284. Restore register.test.ts '
                'when a compatible engine is available. All other sec-default tests still run.',
                flush=True,
            )
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
