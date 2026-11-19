"""Validated software releases and deployment through the rig management API."""
from pathlib import Path
import time
from shared.net import request_json, read_json
from shared.release_manifests.software import MAX_SOFTWARE_BYTES, validate_software


def upload_release(url: str, directory: Path) -> dict:
    """Upload only manifest-validated files as a bounded tar payload."""
    import io
    import tarfile
    from urllib.request import Request, urlopen
    manifest = validate_software(directory, role='rig')
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for name in [*manifest['files'], 'software.json']:
            archive.add(directory / name, arcname=name, recursive=False)
    if payload.tell() > MAX_SOFTWARE_BYTES:
        raise ValueError('software archive exceeds size limit')
    request = Request(url, payload.getvalue(), {'Content-Type': 'application/x-tar'},
                      method='PUT')
    with urlopen(request, timeout=30) as response:
        return read_json(response)


def deployment_action(rig: dict, directory: Path, *, get=request_json,
                      post=request_json, upload=upload_release,
                      clock=time.monotonic, delay=time.sleep):
    """Upload and install through the rig management API, then verify the rig."""
    manifest = validate_software(directory, role='rig')
    from urllib.parse import urlsplit
    base = rig.get('management_url', '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('configure an HTTP(S) management_url for this rig')
    def action(phase):
        phase('uploading release')
        uploaded = upload(base + '/api/releases/' + manifest['release'], directory)
        if uploaded.get('release') != manifest['release']:
            raise ValueError('management API returned the wrong release')
        phase('starting installation')
        try:
            job = post(base + '/api/install', {'release': manifest['release']})
        except (OSError, ValueError) as error:
            raise OSError('Installation request failed; inspect management /api/maintenance before retrying: ' + str(error)) from error
        if not isinstance(job.get('id'), str):
            raise ValueError('management API did not return a job ID')
        deadline = clock() + 600
        while clock() < deadline:
            try:
                current = get(base + '/api/jobs/' + job['id'])
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
