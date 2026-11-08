"""Validated, self-contained display releases; no artwork tooling at runtime."""
import hashlib
import json
import re
from pathlib import Path

SCHEMA = 1
REQUIRED = {'commands.py', 'core.py', 'hardware.py', 'pixels.py', 'storage.py', 'main.py', 'release_identity.py', 'identity.json'}
REQUIRED_ASSETS = {'assets/fonts.json', 'assets/font22.bin', 'assets/font24.bin'}
for state in ('on_air', 'camera_active', 'camera_inactive', 'unknown'):
    for step in (0, 3):
        REQUIRED_ASSETS.add(f'assets/{state}-{step}-0.r')
    if state != 'unknown':
        for phase in range(4):
            REQUIRED_ASSETS.add('assets/%s-motion-%d.bin' % (state, phase))
MAX_RELEASE_BYTES = 64 * 1024 * 1024


def validate_release(directory: Path) -> dict:
    """Validate every payload before an installer touches the device."""
    directory = directory.resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    if not isinstance(manifest, dict):
        raise ValueError('release manifest must be an object')
    if (manifest.get('schema') != SCHEMA or manifest.get('target') != 'pico2w'
            or manifest.get('protocol') != 1 or not isinstance(manifest.get('release'), str)
            or not manifest['release'] or len(manifest['release']) > 64 or not isinstance(manifest.get('files'), dict)):
        raise ValueError('unsupported or incomplete release manifest')
    names = set(manifest['files'])
    if not all(isinstance(name, str) for name in names):
        raise ValueError('release file names must be strings')
    if not REQUIRED <= names or not REQUIRED_ASSETS <= names:
        raise ValueError('release is missing firmware or assets')
    total = 0
    for name, digest in manifest['files'].items():
        path = directory / name
        if (not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts
                or any(part in ('', '.', '..') for part in name.split('/'))
                or path.is_symlink() or not path.resolve().is_relative_to(directory)
                or not path.is_file()):
            raise ValueError('invalid release file: ' + str(name))
        total += path.stat().st_size
        if total > MAX_RELEASE_BYTES:
            raise ValueError('release exceeds size limit')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('release checksum mismatch: ' + name)
    if 'runtime.uf2' not in names or not isinstance(manifest.get('runtime'), str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', manifest['runtime']):
        raise ValueError('release requires a Pico 2 W runtime UF2 and runtime identity')
    identity = json.loads((directory / 'identity.json').read_text())
    if not isinstance(identity, dict):
        raise ValueError('release identity must be an object')
    if any(identity.get(key) != manifest.get(key) for key in ('release', 'protocol', 'target', 'runtime')):
        raise ValueError('release identity mismatch')
    return manifest
