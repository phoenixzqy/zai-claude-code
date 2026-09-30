#!/usr/bin/env python3
"""Launch Claude Code with the repository's privacy opt-outs before startup."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys


SETTINGS_PATH = Path(__file__).resolve().parents[2] / '.claude' / 'settings.json'


def privacy_environment(environment, settings):
    result = {
        name: value for name, value in environment.items()
        if not name.startswith('OTEL_')
        and name not in {'TRACEPARENT', 'TRACESTATE', 'BETA_TRACING_ENDPOINT'}
    }
    result.update(settings['env'])
    return result


def launch_command(binary, arguments, settings, environment):
    for argument in arguments:
        if argument.split('=', 1)[0] in {'--settings', '--setting-sources'}:
            raise ValueError('Privacy settings cannot be replaced through this launcher.')
    executable = shutil.which(binary, path=environment.get('PATH', os.defpath))
    if executable is None:
        raise FileNotFoundError(f'Claude Code executable not found: {binary}')
    return [executable, '--settings', json.dumps(settings), *arguments]


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude-binary', default='claude')
    parser.add_argument('claude_arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    forwarded = args.claude_arguments
    if forwarded[:1] == ['--']:
        forwarded = forwarded[1:]
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        environment = privacy_environment(os.environ, settings)
        command = launch_command(args.claude_binary, forwarded, settings, environment)
        os.execvpe(command[0], command, environment)
    except (OSError, ValueError, KeyError) as error:
        print(f'Privacy launcher: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
