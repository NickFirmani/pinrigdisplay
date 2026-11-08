"""Validated software releases and deployment through the rig management API."""
import hashlib
import json
from pathlib import Path
import re
import time
from .net import request_json


MAX_SOFTWARE_BYTES = 64 * 1024 * 1024


def validate_software(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / 'software.json').read_text())
    if not isinstance(manifest, dict):
        raise ValueError('software manifest must be an object')
    if (manifest.get('schema') != 1 or manifest.get('protocol') != 1 or manifest.get('target') != 'linux'
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


def upload_release(url: str, directory: Path, *, headers: dict) -> dict:
    """Upload only manifest-validated files as a bounded tar payload."""
    import io
    import tarfile
    from urllib.request import Request, urlopen
    from .net import read_json
    manifest = validate_software(directory)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for name in [*manifest['files'], 'software.json']:
            archive.add(directory / name, arcname=name, recursive=False)
    if payload.tell() > MAX_SOFTWARE_BYTES:
        raise ValueError('software archive exceeds size limit')
    request = Request(url, payload.getvalue(), {'Content-Type': 'application/x-tar', **headers}, method='PUT')
    with urlopen(request, timeout=30) as response:
        return read_json(response)


def deployment_action(rig: dict, directory: Path, *, token: str = '',
                      get=request_json, post=request_json, upload=upload_release,
                      clock=time.monotonic, delay=time.sleep):
    """Upload and install through the rig management API, then verify the rig."""
    manifest = validate_software(directory)
    from urllib.parse import urlsplit
    base = rig.get('management_url', '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('configure an HTTP(S) management_url for this rig')
    if not token:
        raise ValueError('configure a maintenance credential')
    headers = {'Authorization': 'Bearer ' + token}
    def action(phase):
        phase('uploading release')
        uploaded = upload(base + '/api/releases/' + manifest['release'], directory, headers=headers)
        if uploaded.get('release') != manifest['release']:
            raise ValueError('management API returned the wrong release')
        phase('starting installation')
        try:
            job = post(base + '/api/install', {'release': manifest['release']}, headers=headers)
        except (OSError, ValueError) as error:
            raise OSError('Installation request failed; inspect management /api/maintenance before retrying: ' + str(error)) from error
        if not isinstance(job.get('id'), str):
            raise ValueError('management API did not return a job ID')
        deadline = clock() + 600
        while clock() < deadline:
            try:
                current = get(base + '/api/jobs/' + job['id'], headers=headers)
            except (OSError, ValueError) as error:
                raise OSError('Lost management connection for job ' + job['id'] + '; inspect /api/maintenance before retrying: ' + str(error)) from error
            if current.get('id') != job['id']:
                raise ValueError('management job identity mismatch')
            if current.get('state') == 'failed':
                raise OSError('Rig installation failed: ' + str(current.get('error', 'inspect rig manager logs')))
            if current.get('state') == 'succeeded':
                break
            if current.get('state') != 'running':
                raise ValueError('invalid management job state')
            phase(str(current.get('phase', 'installing'))[:120])
            delay(1)
        else:
            raise OSError('rig installation timed out; inspect its management job before retrying')
        phase('verifying')
        deadline = clock() + 30
        while clock() < deadline:
            try:
                status = get(rig['url'].rstrip('/') + '/api/status')
                if status.get('rig') == rig['id'] and status.get('software_release') == manifest['release']:
                    return {'release': manifest['release'], 'rig': rig['id'], 'display_connected': status.get('host', {}).get('result', {}).get('connected', False)}
            except (OSError, ValueError):
                pass
            delay(1)
        raise OSError('rig software version verification timed out; inspect rig logs')
    return action
