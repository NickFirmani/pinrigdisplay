"""Collect a private host configuration for a first-time offline installation."""
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from tools.install_linux import validate_config


def ask(label: str, default: str = '') -> str:
    """Prompt for a value with an optional default."""
    hint = f' [{default}]' if default else ''
    return input(f'{label}{hint}: ').strip() or default


def ask_url(label: str, default: str, schemes: tuple[str, ...]) -> str:
    """Prompt for a URL without embedded credentials."""
    while True:
        value = ask(label, default)
        try:
            url = urlsplit(value)
            if (url.scheme in schemes and url.hostname and url.port != 0 and not any(c.isspace() for c in value)
                    and '@' not in url.netloc and not url.query and not url.fragment):
                return value.rstrip('/')
        except ValueError:
            pass
        print(f'Enter a valid {"/".join(schemes)} URL without credentials.')


def ask_id(default: str, used: set[str]) -> str:
    """Prompt for a valid, unique rig ID."""
    while True:
        value = ask('Rig ID', default)
        if re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', value) and value not in used:
            return value
        print('Enter a unique rig ID using letters, digits, dots, underscores, colons or hyphens.')


def rig_settings(serial_directory: Path) -> dict:
    rig_id = ask_id('rig1', set())
    devices = sorted(path for path in serial_directory.glob('*') if path.exists())
    if devices:
        print('USB serial devices:', *(str(path) for path in devices), sep='\n  ')
    default = str(devices[0]) if len(devices) == 1 else ''
    while True:
        serial = ask('Pico USB serial path', default)
        if re.fullmatch(r'/dev/[/A-Za-z0-9_.:-]+', serial):
            return {'id': rig_id, 'serial': serial}
        print('Enter a /dev/ path. Prefer the stable path under /dev/serial/by-id/.')


def stream_settings() -> dict:
    obs_url = ask_url('OBS WebSocket URL', 'ws://127.0.0.1:4455', ('ws', 'wss'))
    rigs = []
    used = set()
    for number in range(1, 33):
        rig_id = ask_id(f'rig{number}', used)
        used.add(rig_id)
        url = ask_url('Rig dashboard URL', f'http://{rig_id}:48194', ('http', 'https'))
        host = urlsplit(url).hostname
        address = f'[{host}]' if ':' in host else host
        management = ask_url('Rig management URL', f'{urlsplit(url).scheme}://{address}:48198', ('http', 'https'))
        scenes = []
        while not scenes:
            scene_names = ask('OBS program scenes, comma-separated', f'Rig {number}, MEGA PINBALL')
            scenes = [scene.strip() for scene in scene_names.split(',') if scene.strip()]
            if not scenes:
                print('Enter at least one OBS program scene.')
        rigs.append({'id': rig_id, 'url': url, 'management_url': management,
                     'scenes': scenes})
        if number == 32 or ask('Add another rig? (y/N)', 'n').lower() not in ('y', 'yes'):
            break
    return {'obs_url': obs_url, 'rigs': rigs}


def generate_config(role: str, path: Path, *, serial_directory: Path = Path('/dev/serial/by-id')) -> None:
    """Prompt for the host settings and write a new config with mode 0600."""
    print(f'Configure PinRig {role} on this host.')
    config = {'role': role, 'bind': '0.0.0.0'}
    config.update(rig_settings(serial_directory) if role == 'rig' else stream_settings())
    validate_config(config)
    with NamedTemporaryFile(mode='w', dir=path.parent) as temporary:
        json.dump(config, temporary, indent=2)
        temporary.write('\n')
        temporary.flush()
        os.link(temporary.name, path)
    print(f'Saved private config to {path}.')
