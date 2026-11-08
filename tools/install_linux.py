"""Root-only, rerunnable Linux installation from a verified offline wheelhouse."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import shlex
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def run(*args):
    subprocess.run(args, check=True, timeout=300)


def get_json(url: str | Request) -> dict:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read(1024 * 1024))


def verify_service(role: str, config: dict, release: str, *, get=get_json, clock=time.monotonic, delay=time.sleep) -> None:
    """Wait for the installed process to report its exact software release."""
    bind = config.get('bind', '127.0.0.1')
    if bind in ('0.0.0.0', '::'):
        bind = '127.0.0.1'
    port = config.get('port', 48194 if role == 'rig' else 48195)
    deadline = clock() + 30
    while clock() < deadline:
        try:
            status = get('http://%s:%s/api/status' % (bind, port))
            if status.get('software_release') == release and (role != 'rig' or status.get('rig') == config['id']):
                return
        except (OSError, ValueError):
            pass
        delay(.5)
    raise OSError('installed service did not report its release; inspect journalctl -u pinrig-' + role)


def validate_config(config: dict) -> str:
    """Validate configuration before any accounts, files or services change."""
    if not isinstance(config, dict):
        raise ValueError('configuration must be an object')
    role = config.get('role', 'rig')
    if role not in ('rig', 'stream'):
        raise ValueError('role must be rig or stream')
    port = config.get('port', 48194 if role == 'rig' else 48195)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port must be between 1 and 65535')
    for key in ('bind', 'videonode_url', 'bootsel_mount', 'management_bind'):
        if key in config and (not isinstance(config[key], str) or not re.fullmatch(r'[A-Za-z0-9_./:=@-]+', config[key])):
            raise ValueError('invalid ' + key)
    management_port = config.get('management_port', 48198)
    if type(management_port) is not int or not 1 <= management_port <= 65535 or role == 'rig' and management_port == port:
        raise ValueError('management_port must be a distinct valid port')
    if role == 'rig':
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', config.get('id', '')):
            raise ValueError('invalid rig identity')
        if not re.fullmatch(r'/dev/[/A-Za-z0-9_.:-]+', config.get('serial', '')):
            raise ValueError('select an actual /dev/serial/by-id device')
    elif not isinstance(config.get('rigs'), list) or not config['rigs']:
        raise ValueError('stream configuration requires rigs')
    return role


def write_release_metadata(path: Path, text: str) -> None:
    """Never follow a service-created link when writing privileged metadata."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(text)


def verify_manager(config: dict, token: str, *, get=get_json, clock=time.monotonic, delay=time.sleep) -> None:
    """Verify the independent management API, including its credential."""
    bind = config.get('management_bind', config.get('bind', '0.0.0.0'))
    if bind == '0.0.0.0':
        bind = '127.0.0.1'
    url = 'http://%s:%s/api/health' % (bind, config.get('management_port', 48198))
    request = Request(url, headers={'Authorization': 'Bearer ' + token})
    deadline = clock() + 30
    while clock() < deadline:
        try:
            if get(request).get('management_schema') == 1:
                return
        except (OSError, ValueError):
            pass
        delay(.5)
    raise OSError('management API did not start; inspect journalctl -u pinrig-manager')


def setup_manager(bundle: Path, config: dict, root: Path, runner, *, verify=verify_manager) -> None:
    """Bootstrap the separate root-owned manager; never called by its update API."""
    base = root / 'opt/pinrig-manager'
    helper = root / 'usr/local/lib/pinrig/install_linux.py'
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__), helper)
    helper.chmod(0o644)
    settings = root / 'etc/pinrig-rig.json'
    settings.write_text(json.dumps({key: value for key, value in config.items()
                                   if key not in ('maintenance_token', 'obs_token')}))
    settings.chmod(0o600)
    unit = root / 'etc/systemd/system/pinrig-manager.service'
    if unit.exists():
        runner('systemctl', 'stop', 'pinrig-manager.service')
    runner(sys.executable, '-m', 'venv', str(base))
    runner(str(base / 'bin/pip'), 'install', '--no-index', '--only-binary=:all:', '--find-links', str(bundle / 'wheels'),
           '--upgrade', '--force-reinstall', 'pinrig-producers')
    state = root / 'var/lib/pinrig-manager'
    state.mkdir(parents=True, exist_ok=True, mode=0o755)
    unit.write_text('[Unit]\nDescription=Pinrig software management API\nAfter=network.target\n'
        '[Service]\nUser=root\nEnvironmentFile=' + str(root / 'etc/pinrig-rig.env') + '\n'
        'ExecStart=' + str(base / 'bin/pinrig-manager') + ' --bind ' + config.get('management_bind', config.get('bind', '0.0.0.0')) +
        ' --port ' + str(config.get('management_port', 48198)) + '\nRestart=on-failure\nRestartSec=3\n'
        'TimeoutStopSec=660\nUMask=0022\n[Install]\nWantedBy=multi-user.target\n')
    runner('systemctl', 'daemon-reload')
    runner('systemctl', 'enable', '--now', 'pinrig-manager.service')
    values = (root / 'etc/pinrig-rig.env').read_text().splitlines()
    raw = next((line.split('=', 1)[1] for line in values if line.startswith('PINRIG_MAINTENANCE_TOKEN=')), '')
    parsed = shlex.split(raw)
    if not parsed:
        raise ValueError('management credential is missing from rig environment')
    verify(config, parsed[0])


def install(bundle: Path, config: dict, *, root: Path = Path('/'), runner=run, verify=verify_service, management: bool = True) -> None:
    if os.geteuid() != 0:
        raise ValueError('run installer with sudo')
    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11+ required')
    manifest = json.loads((bundle / 'software.json').read_text())
    release = manifest['release']
    if manifest.get('schema') != 1 or manifest.get('protocol') != 1 or manifest.get('target') != 'linux' or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', release) or release in ('.', '..', 'current', 'current.new'):
        raise ValueError('invalid software release')
    for name, digest in manifest['files'].items():
        path = bundle / name
        if not path.resolve().is_relative_to(bundle.resolve()) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('invalid software payload: ' + name)
    role = validate_config(config)
    try:
        account = pwd.getpwnam('pinrigdisplay')
    except KeyError:
        runner('useradd', '--system', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin', 'pinrigdisplay')
        account = pwd.getpwnam('pinrigdisplay')
    base = root / ('opt/pinrig-' + role)
    base.mkdir(parents=True, exist_ok=True)
    target = base / release
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    marker = target / '.bundle-sha256'
    if marker.exists() and marker.read_text() != fingerprint:
        raise ValueError('release name already installed with different contents; choose a new release')
    if not marker.exists():
        current = base / 'current'
        if current.exists() and current.resolve() == target:
            raise ValueError('cannot overwrite the active release; choose a new release')
        target.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError('release directory must not be a symlink')
        os.chown(target, account.pw_uid, account.pw_gid, follow_symlinks=False)
        runner('runuser', '-u', 'pinrigdisplay', '--', sys.executable, '-m', 'venv', str(target))
        runner('runuser', '-u', 'pinrigdisplay', '--', str(target / 'bin/pip'), 'install', '--no-index', '--only-binary=:all:', '--find-links', str(bundle / 'wheels'),
            'pinrig-producers[' + ('rig' if role == 'rig' else 'obs') + ']', *(['mpremote'] if role == 'rig' else []))
        write_release_metadata(marker, fingerprint)
    # Mark the exact deployed bundle separately from Python package versions.
    write_release_metadata(target / 'release.json', json.dumps({'release': release}))
    state = root / ('var/lib/pinrig-host' if role == 'rig' else 'var/lib/pinrig-stream')
    state.mkdir(parents=True, exist_ok=True)
    (state / 'releases').mkdir(exist_ok=True)
    os.chown(state, account.pw_uid, account.pw_gid)
    os.chown(state / 'releases', account.pw_uid, account.pw_gid, follow_symlinks=False)
    env = root / ('etc/pinrig-' + role + '.env')
    if not env.exists():
        for key in ('obs_token', 'maintenance_token'):
            if not isinstance(config.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', config[key]):
                raise ValueError('first install needs 24–128 character URL-safe obs_token and maintenance_token')
        env.write_text('PINRIG_OBS_TOKEN=' + config['obs_token'] + '\nPINRIG_MAINTENANCE_TOKEN=' + config['maintenance_token'] + '\n')
        env.chmod(0o600)
    if role == 'rig':
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', config['id']):
            raise ValueError('invalid rig identity')
        serial = config['serial']
        if not serial.startswith('/dev/') or not re.fullmatch(r'[/A-Za-z0-9_.:-]+', serial):
            raise ValueError('select an actual /dev/serial/by-id device')
        runner('usermod', '-a', '-G', 'dialout', 'pinrigdisplay')
        args = ['--rig', config['id'], '--serial', serial, '--bind', config.get('bind', '0.0.0.0'),
                '--videonode-url', config.get('videonode_url', 'http://127.0.0.1:8090'), '--port', str(config.get('port', 48194))]
        if config.get('bootsel_mount'):
            args += ['--bootsel-mount', config['bootsel_mount']]
        entry = 'pinrig-rig'
    else:
        settings = state / 'config.json'
        write_release_metadata(settings, json.dumps({'rigs': config['rigs'], 'obs_url': config.get('obs_url', 'ws://127.0.0.1:4455')}))
        os.chown(settings, account.pw_uid, account.pw_gid, follow_symlinks=False)
        args = ['--config', str(settings), '--bind', config.get('bind', '127.0.0.1'), '--port', str(config.get('port', 48195))]
        entry = 'pinrig-stream'
    if any(not re.fullmatch(r'[A-Za-z0-9_./:=@-]+', arg) for arg in args):
        raise ValueError('invalid service argument')
    # Firmware uploads and service replacement must never overlap.
    import fcntl
    installation_lock = os.fdopen(os.open(state / 'maintenance.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644), 'a')
    try:
        fcntl.flock(installation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        installation_lock.close()
        raise ValueError('another installation is in progress') from error
    os.chown(state / 'maintenance.lock', account.pw_uid, account.pw_gid, follow_symlinks=False)
    try:
        unit = 'pinrig-' + role
        if (root / ('etc/systemd/system/' + unit + '.service')).exists():
            runner('systemctl', 'stop', unit + '.service')
        for name in ('interactions.sqlite3', 'interactions.sqlite3-wal', 'interactions.sqlite3-shm', 'maintenance.json'):
            managed = state / name
            if managed.is_symlink():
                raise ValueError('managed state must not be a symlink: ' + name)
            if managed.exists():
                os.chown(managed, account.pw_uid, account.pw_gid, follow_symlinks=False)
        link = base / 'current.new'
        link.unlink(missing_ok=True)
        link.symlink_to(target)
        link.replace(base / 'current')
        (root / ('etc/systemd/system/' + unit + '.service')).write_text(
            '[Unit]\nDescription=Pinrig ' + role + '\nAfter=network.target\n[Service]\n'
            'User=pinrigdisplay\nGroup=pinrigdisplay\n' + ('SupplementaryGroups=dialout\n' if role == 'rig' else '') +
            'EnvironmentFile=' + str(env) + '\nEnvironment=PATH=' + str(base / 'current/bin') + ':/usr/bin:/bin\n'
            'ExecStart=' + str(base / 'current/bin' / entry) + ' ' + ' '.join(args) + '\n'
            'Restart=on-failure\nRestartSec=3\nTimeoutStopSec=180\nUMask=0027\n'
            '[Install]\nWantedBy=multi-user.target\n')
        runner('systemctl', 'daemon-reload')
        runner('systemctl', 'enable', '--now', unit + '.service')
        runner('systemctl', 'is-active', '--quiet', unit + '.service')
        verify(role, config, release)
    finally:
        installation_lock.close()
    if role == 'rig' and management:
        setup_manager(bundle, config, root, runner)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--application-only', action='store_true', help='update application using an already bootstrapped manager')
    args = parser.parse_args()
    install(args.bundle.resolve(), json.loads(args.config.read_text()), management=not args.application_only)


if __name__ == '__main__':
    main()
