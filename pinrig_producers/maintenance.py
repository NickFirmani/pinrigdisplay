"""Serialized, persisted maintenance jobs and a bounded mpremote installer."""
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from .releases import validate_release


class Jobs:
    """One active job; retain its outcome across process restarts."""
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.worker = None
        self.value = {'state': 'idle'}
        if path.exists():
            self.value = json.loads(path.read_text())
            if self.value.get('state') == 'running':
                self.value.update(state='failed', error='Service restarted; inspect target and retry installation')
                self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.value))
        temporary.replace(self.path)

    def wait(self) -> None:
        """Drain maintenance before releasing service resources."""
        if self.worker is not None:
            self.worker.join()

    def status(self) -> dict:
        with self.lock:
            return dict(self.value)

    def phase(self, phase: str) -> None:
        with self.lock:
            self.value['phase'] = phase
            self._save()

    def start(self, action, *, launch=None) -> dict:
        with self.lock:
            if self.value['state'] == 'running':
                raise ValueError('maintenance already running')
            self.value = {'id': uuid.uuid4().hex, 'state': 'running', 'phase': 'queued'}
            self._save()
        def work():
            try:
                result = action(self.phase)
                with self.lock:
                    self.value.update(state='succeeded', result=result)
                    self._save()
            except Exception as error:
                logging.getLogger(__name__).exception('Maintenance job failed')
                with self.lock:
                    self.value.update(state='failed', error=str(error)[:500])
                    self._save()
        try:
            if launch:
                launch(work)
            else:
                self.worker = threading.Thread(target=work, daemon=False)
                self.worker.start()
        except Exception as error:
            with self.lock:
                self.value.update(state='failed', error=str(error)[:500])
                self._save()
            raise
        return self.status()


@contextmanager
def installation_lock(path):
    """Coordinate firmware jobs with software upgrades across processes."""
    if path is None:
        yield
        return
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('another installation is in progress') from error
        yield


@contextmanager
def exclusive_usb(host):
    """Release USB even when entering maintenance partially fails."""
    try:
        host.begin_maintenance()
        yield
    finally:
        host.end_maintenance()


class FirmwareInstaller:
    def __init__(self, host, port: str, *, run=subprocess.run, clock=time.monotonic, delay=time.sleep, lock_path=None, bootsel_mount=None):
        self.bootsel_mount = bootsel_mount
        self.lock_path = lock_path
        self.host, self.port = host, port
        self.run, self.clock, self.delay = run, clock, delay

    def install(self, directory: Path, phase, *, clean=False, runtime=False) -> dict:
        manifest = validate_release(directory)
        def remote(*args):
            # Bound subprocess lifetime and avoid returning device/credential output.
            try:
                self.run(['mpremote', 'connect', self.port, *args], check=True,
                         timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as error:
                detail = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else str(error.stderr or '')
                raise OSError('Firmware tool failed; check USB ownership/path and device storage: ' + detail[-300:]) from error
        with installation_lock(self.lock_path):
            with exclusive_usb(self.host):
                if runtime:
                    if self.bootsel_mount is None:
                        raise ValueError('configure --bootsel-mount and mount the Pico in BOOTSEL mode')
                    mount = self.bootsel_mount.resolve()
                    info = (mount / 'INFO_UF2.TXT').read_text()
                    if not os.path.ismount(mount) or 'RP2350' not in info:
                        raise ValueError('BOOTSEL target must be a mounted RP2350 volume')
                    phase('installing runtime')
                    with (directory / 'runtime.uf2').open('rb') as source, (mount / 'firmware.uf2').open('wb') as target:
                        import shutil
                        shutil.copyfileobj(source, target)
                        target.flush()
                        os.fsync(target.fileno())
                    phase('waiting for USB runtime')
                    deadline = self.clock() + 30
                    while True:
                        try:
                            remote('exec', 'import sys')
                            break
                        except (OSError, subprocess.SubprocessError):
                            if self.clock() >= deadline:
                                raise OSError('runtime USB did not return; inspect device path and BOOTSEL installation')
                            self.delay(1)
                phase('uploading')
                if clean:
                    remote('exec', "import os\ntry: os.remove('interactions.json')\nexcept OSError as e:\n if e.args[0] != 2: raise")
                # Copy only validated files, never arbitrary extra directory contents.
                directories = sorted({str(Path(name).parent) for name in manifest['files'] if '/' in name}, key=lambda v: (v.count('/'), v))
                for name in directories:
                    if name != '.':
                        remote('exec', 'import os\ntry: os.mkdir(' + repr(name) + ')\nexcept OSError as e:\n if e.args[0] != 17: raise')
                for index, name in enumerate(sorted(manifest['files'], key=lambda name: (name == 'main.py', name)), 1):
                    if name == 'runtime.uf2':
                        continue
                    phase('uploading %d/%d' % (index, len(manifest['files'])))
                    remote('fs', 'cp', str(directory / name), ':' + name)
                phase('resetting')
                remote('reset')
            phase('verifying')
            deadline = self.clock() + 30
            while self.clock() < deadline:
                self.host.tick()
                with self.host.lock:
                    status = self.host.device_status
                    if status and status.get('firmware', {}).get('release') == manifest['release']:
                        expected_runtime = manifest['runtime'].split('.')
                        actual_runtime = status.get('runtime_version')
                        if actual_runtime != [int(part) for part in expected_runtime]:
                            raise OSError('runtime version mismatch; use BOOTSEL runtime installation for ' + manifest['runtime'])
                        if not status.get('healthy'):
                            raise OSError('firmware installed but display is unhealthy')
                        return {'release': manifest['release'], 'displayed_state': status.get('displayed_state')}
                self.delay(.5)
            raise OSError('firmware version verification timed out; inspect USB and retry')
