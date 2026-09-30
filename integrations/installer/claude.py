"""Run the native Claude CLI with this fork's privacy and Copilot integration."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
import sys
import subprocess
import tempfile

import copilot
import privacy


DIRECTORY = Path(__file__).resolve().parent


@contextmanager
def terminal_keys():
    if os.name == 'nt':
        import msvcrt

        def read_key():
            key = msvcrt.getwch()
            if key in ('\x00', '\xe0'):
                return {'H': 'up', 'P': 'down'}.get(msvcrt.getwch(), '')
            return key

        yield read_key
    else:
        import select
        import termios
        import tty

        descriptor = sys.stdin.fileno()
        original = termios.tcgetattr(descriptor)

        def read_key():
            key = os.read(descriptor, 1).decode()
            if key == '\x1b':
                sequence = ''
                for _ in range(2):
                    if not select.select([descriptor], [], [], 0.1)[0]:
                        break
                    sequence += os.read(descriptor, 1).decode()
                return {'[A': 'up', '[B': 'down', 'OA': 'up', 'OB': 'down'}.get(sequence, '\x1b')
            if not key:
                raise KeyboardInterrupt
            return key

        try:
            tty.setcbreak(descriptor)
            yield read_key
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, original)


def choose(title, choices):
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    if not choices:
        raise copilot.CopilotError('No tool-calling models are available to this Copilot account.')
    selected = 0
    console = Console()
    with Live(console=console, screen=True, auto_refresh=False) as display, terminal_keys() as read_key:
        while True:
            text = Text()
            visible = max(1, console.size.height - 6)
            start = max(0, selected - visible + 1)
            for position in range(start, min(len(choices), start + visible)):
                label = choices[position]
                text.append(f'{" >" if position == selected else "  "} {position + 1}. {label}\n',
                            style='bold cyan' if position == selected else '')
            text.append('\nUp/Down to select, Enter to continue, Esc or Ctrl-C to cancel.')
            display.update(Panel(text, title=title, border_style='blue'), refresh=True)
            key = read_key()
            if key in ('\r', '\n'):
                return selected
            if key in ('\x1b', '\x03', 'q'):
                raise KeyboardInterrupt
            if key in ('up', 'k'):
                selected = (selected - 1) % len(choices)
            elif key in ('down', 'j'):
                selected = (selected + 1) % len(choices)
            elif key and key in '123456789' and int(key) <= len(choices):
                selected = int(key) - 1


def interactive_provider(arguments):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if arguments == ['auth', 'login']:
        return True
    # Hosts attach session identity and resources even to a fresh interactive launch.
    values = {'--session-id', '--settings', '--add-dir', '--append-system-prompt-file'}
    switches = {'--dangerously-skip-permissions'}
    position = 0
    while position < len(arguments):
        option, separator, value = arguments[position].partition('=')
        if option in switches and not separator:
            position += 1
        elif option in values:
            if separator:
                if not value:
                    return False
                position += 1
            else:
                if position + 1 >= len(arguments) or arguments[position + 1].startswith('-'):
                    return False
                position += 2
        else:
            return False
    return True


def copilot_startup_model(arguments):
    state = copilot.DEFAULT_STATE
    if arguments == ['auth', 'login'] or not (state / 'access-token').is_file():
        copilot.login(state, tui=True)
    if arguments == ['auth', 'login']:
        return None
    available = [entry['id'] for entry in copilot.models(state)
                 if entry.get('capabilities', {}).get('supports', {}).get('tool_calls')]
    return available[choose('Select GitHub Copilot model', available)]


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
        if interactive_provider(arguments):
            provider = choose('Select login method', [
                'Claude / Anthropic / 3rd-party platform (native Claude Code)',
                'GitHub Copilot account',
            ])
            if provider == 1:
                model = copilot_startup_model(arguments)
                if arguments == ['auth', 'login']:
                    return 0
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
    except (OSError, ValueError, KeyError, TypeError, ImportError, copilot.CopilotError) as error:
        print(f'Claude launcher: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
