"""Run the native Claude CLI with this fork's privacy and Copilot integration."""

import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile

import copilot
import privacy


DIRECTORY = Path(__file__).resolve().parent


def configured_arguments(arguments, settings):
    forwarded = []
    combined = {}
    position = 0
    while position < len(arguments):
        argument = arguments[position]
        if argument == '--':
            forwarded.extend(arguments[position:])
            break
        if argument == '--settings' or argument.startswith('--settings='):
            if argument == '--settings':
                position += 1
                if position == len(arguments):
                    raise ValueError('--settings requires a file path or JSON object.')
                value = arguments[position]
            else:
                value = argument.split('=', 1)[1]
            custom = json.loads(value) if value.lstrip().startswith('{') else json.loads(Path(value).read_text())
            if not isinstance(custom, dict) or not isinstance(custom.get('env', {}), dict):
                raise ValueError('Settings must be a JSON object with an object-valued env.')
            combined.update(custom)
        else:
            forwarded.append(argument)
        position += 1
    combined['env'] = {**combined.get('env', {}), **settings['env']}
    combined.update({name: value for name, value in settings.items() if name != 'env'})
    return ['--settings', json.dumps(combined), *forwarded]


def copilot_arguments(arguments):
    forwarded = list(arguments)
    selected = None
    for position, argument in enumerate(arguments):
        if argument == '--':
            break
        if argument == '--model' and position + 1 < len(arguments):
            model = arguments[position + 1]
            target = position + 1
        elif argument.startswith('--model='):
            model = argument.split('=', 1)[1]
            target = position
        else:
            continue
        selected = None
        if model.startswith('github-copilot/'):
            selected = model.removeprefix('github-copilot/')
            if not selected:
                raise ValueError('Specify a model ID after github-copilot/.')
            forwarded[target] = selected if target != position else '--model=' + selected
    return selected, forwarded


def native_arguments(arguments, settings):
    if arguments[:2] in (['plugin', 'test'], ['plugins', 'test']):
        return list(arguments)
    return ['--settings', settings, *arguments]


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        binary = Path(json.loads((DIRECTORY / 'runtime.json').read_text())['claude_binary'])
        if not binary.is_absolute() or not binary.is_file():
            raise ValueError('Native Claude executable is missing; rerun the install script.')
        settings = json.loads((DIRECTORY / 'settings.json').read_text())
        environment = privacy.privacy_environment(os.environ, settings)
        if arguments[:1] == ['copilot']:
            return copilot.main(arguments[1:])
        model, forwarded = copilot_arguments(arguments)
        configured = configured_arguments(forwarded, settings)
        command = native_arguments(configured[2:], configured[1])
        if json.loads(configured[1]) != settings:
            with tempfile.TemporaryDirectory(prefix='zai-claude-settings-') as temporary:
                snapshot = Path(temporary) / 'settings.json'
                copilot.write_private(snapshot, configured[1])
                command = native_arguments(configured[2:], str(snapshot))
                if model:
                    return copilot.run(copilot.DEFAULT_STATE, model, command)
                result = subprocess.run([str(binary), *command], env=environment, check=False)
                return result.returncode if result.returncode >= 0 else 128 - result.returncode
        if model:
            return copilot.run(copilot.DEFAULT_STATE, model, command)
        os.execve(str(binary), [str(binary), *command], environment)
    except (OSError, ValueError, KeyError, TypeError, copilot.CopilotError) as error:
        print(f'Claude launcher: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
