"""Validate the manifest and files of an offline Linux software release."""
import hashlib
import json
from pathlib import Path
import re


SOFTWARE_ROLES = ('rig', 'stream')
MAX_SOFTWARE_BYTES = 64 * 1024 * 1024


def validate_software(directory: Path, *, role: str) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / 'software.json').read_text())
    if not isinstance(manifest, dict):
        raise ValueError('software manifest must be an object')
    if (manifest.get('schema') != 1 or manifest.get('protocol') != 1 or manifest.get('target') != 'linux'
            or role not in SOFTWARE_ROLES or manifest.get('role') != role
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', manifest.get('release', ''))
            or manifest['release'] in ('.', '..', 'current', 'current.new') or not isinstance(manifest.get('files'), dict)
            or 'install_linux.py' not in manifest['files'] or not all(isinstance(n, str) for n in manifest['files'])
            or not any(n.startswith('wheels/') for n in manifest['files'])):
        raise ValueError('invalid software manifest')
    if any(name != 'install_linux.py' and not (name.startswith('wheels/') and name.count('/') == 1 and name.endswith('.whl')) for name in manifest['files']):
        raise ValueError('software release must contain only its installer and wheels')
    total = 0
    if len(manifest['files']) > 256:
        raise ValueError('too many software payload files')
    for name, digest in manifest['files'].items():
        path = directory / name
        if Path(name).is_absolute() or any(part in ('', '.', '..') for part in name.split('/')) or path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
            raise ValueError('invalid software payload: ' + name)
        total += path.stat().st_size
        if total > MAX_SOFTWARE_BYTES:
            raise ValueError('software release exceeds size limit')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('invalid software payload: ' + name)
    return manifest
