"""Install this fork's Copilot gateway and the official Claude Code CLI."""

from pathlib import Path
import runpy


if __name__ == '__main__':
    installer = Path(__file__).resolve().parents[1] / 'integrations' / 'installer' / 'install.py'
    runpy.run_path(str(installer), run_name='__main__')
