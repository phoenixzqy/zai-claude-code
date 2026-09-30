"""Run every integration's unit tests without forge credentials or model calls."""

from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    suites = sorted((root / 'integrations').glob('*/tests'))
    if not suites:
        raise RuntimeError('No integration test suites found.')
    failed = False
    for tests in suites:
        result = subprocess.run(
            [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(tests), '-v'],
            cwd=root, check=False, timeout=600,
        )
        failed = result.returncode != 0 or failed
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
