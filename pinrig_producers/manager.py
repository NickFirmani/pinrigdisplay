"""Independent rig software-management API; survives display-service updates."""
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
from urllib.parse import urlsplit
from pinrig_protocol.http import HTTPServer, make_handler
from .deployment import MAX_SOFTWARE_BYTES, validate_software
from .maintenance import Jobs


def release_name(value: object) -> str:
    """Accept a single immutable release identifier, never a path."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value) or value in ('.', '..', 'current', 'current.new'):
        raise ValueError('invalid software release name')
    return value


def stage_release(stream, length: int, releases: Path, release: str) -> dict:
    """Extract regular files into a private staging area, validate, then publish."""
    release_name(release)
    if not 0 < length <= MAX_SOFTWARE_BYTES:
        raise ValueError('software archive exceeds size limit')
    releases.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=releases) as temp:
        staging = Path(temp)
        archive_path = staging / 'upload.tar'
        with archive_path.open('wb') as output:
            remaining = length
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise ValueError('incomplete software archive')
                output.write(chunk)
                remaining -= len(chunk)
        payload = staging / 'payload'
        payload.mkdir()
        total = 0
        names = set()
        with tarfile.open(archive_path, 'r:') as archive:
            for member in archive:
                name = member.name
                if (not member.isfile() or Path(name).is_absolute()
                        or any(part in ('', '.', '..') for part in name.split('/'))
                        or name in names or len(names) >= 257):
                    raise ValueError('archive must contain unique regular relative files')
                total += member.size
                if total > MAX_SOFTWARE_BYTES:
                    raise ValueError('expanded software archive exceeds size limit')
                names.add(name)
                path = payload / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open('wb') as target:
                    shutil.copyfileobj(source, target)
        manifest = validate_software(payload)
        if manifest['release'] != release or names != set(manifest['files']) | {'software.json'}:
            raise ValueError('archive does not match release manifest')
        destination = releases / release
        if destination.exists():
            if validate_software(destination) != manifest:
                raise ValueError('release already staged with different contents')
        else:
            # Payloads are readable by the unprivileged application installer.
            payload.chmod(0o755)
            for path in payload.rglob('*'):
                path.chmod(0o755 if path.is_dir() else 0o644)
            payload.rename(destination)
    return {'release': release}


class SoftwareInstaller:
    """Invoke only the root-owned bootstrap helper and fixed rig configuration."""
    def __init__(self, releases: Path, helper: Path, config: Path, *, run=subprocess.run):
        self.releases, self.helper, self.config, self.run = releases, helper, config, run

    def install(self, release: str, phase) -> dict:
        directory = self.releases / release_name(release)
        manifest = validate_software(directory)
        phase('installing rig software')
        try:
            self.run(['/usr/bin/python3', str(self.helper), '--bundle', str(directory),
                      '--config', str(self.config), '--application-only'],
                     check=True, timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else str(error.stderr or '')
            raise OSError('Local rig installation failed: ' + detail[-400:]) from error
        return {'release': manifest['release']}


def make_manager_handler(jobs: Jobs, installer: SoftwareInstaller, token: str):
    class Handler(make_handler(jobs)):
        def authorized(self) -> bool:
            if not token or not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
                self.send_json(403, {'error': 'maintenance credential required'})
                return False
            try:
                origin = self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    raise ValueError('cross-origin requests are not accepted')
            except ValueError as error:
                self.send_json(403, {'error': str(error)})
                return False
            return True

        def length(self, content_type: str, maximum: int) -> int:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != content_type or not 0 < length <= maximum:
                raise ValueError('invalid request content type or length')
            return length

        def do_GET(self):
            if not self.authorized():
                return
            if self.path == '/api/health':
                self.send_json(200, {'management_schema': 1, 'process': 'running'})
            elif self.path == '/api/maintenance':
                self.send_json(200, jobs.status())
            elif self.path.startswith('/api/jobs/'):
                current = jobs.status()
                if self.path.removeprefix('/api/jobs/') != current.get('id'):
                    self.send_json(404, {'error': 'job not found'})
                else:
                    self.send_json(200, current)
            else:
                self.send_json(404, {'error': 'route not found'})

        def do_PUT(self):
            if not self.authorized():
                return
            if not self.path.startswith('/api/releases/'):
                self.send_json(404, {'error': 'route not found'})
                return
            try:
                release = release_name(self.path.removeprefix('/api/releases/'))
                # Serialize catalog writes with installation and other uploads.
                with catalog_lock:
                    result = stage_release(self.rfile, self.length('application/x-tar', MAX_SOFTWARE_BYTES), installer.releases, release)
                self.send_json(200, result)
            except (OSError, ValueError, tarfile.TarError) as error:
                self.send_json(422, {'error': str(error)})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/api/install':
                self.send_json(404, {'error': 'route not found'})
                return
            try:
                value = json.loads(self.rfile.read(self.length('application/json', 8192)))
                if not isinstance(value, dict) or set(value) != {'release'}:
                    raise ValueError('expected release')
                release = release_name(value['release'])
                with catalog_lock:
                    validate_software(installer.releases / release)
                    self.send_json(202, jobs.start(lambda phase: installer.install(release, phase)))
            except (OSError, ValueError) as error:
                self.send_json(422, {'error': str(error)})
    catalog_lock = threading.Lock()
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=48198)
    parser.add_argument('--state', type=Path, default=Path('/var/lib/pinrig-manager'))
    parser.add_argument('--installer', type=Path, default=Path('/usr/local/lib/pinrig/install_linux.py'))
    parser.add_argument('--config', type=Path, default=Path('/etc/pinrig-rig.json'))
    args = parser.parse_args()
    token = os.environ.get('PINRIG_MAINTENANCE_TOKEN', '')
    if not token:
        parser.error('PINRIG_MAINTENANCE_TOKEN must be configured')
    args.state.mkdir(parents=True, exist_ok=True)
    releases = args.state / 'releases'
    releases.mkdir(exist_ok=True, mode=0o755)
    jobs = Jobs(args.state / 'maintenance.json')
    installer = SoftwareInstaller(releases, args.installer, args.config)
    server = HTTPServer((args.bind, args.port), make_manager_handler(jobs, installer, token))
    server.daemon_threads = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: threading.Thread(target=server.shutdown).start())
    try:
        server.serve_forever()
    finally:
        server.server_close()
        jobs.wait()


if __name__ == '__main__':
    main()
