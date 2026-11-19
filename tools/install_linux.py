"""Root-only, rerunnable Linux installation from a verified offline wheelhouse."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.request import ProxyHandler, build_opener

from shared.release_manifests.software import SOFTWARE_ROLES, validate_software


SERVICE_FAMILIES = {
    'pinrig-rig.service': ('pinrig-rig', 'pinrig-host', 'display-controller'),
    'pinrig-stream.service': ('pinrig-stream', 'pinrig-obs'),
    'pinrig-manager.service': ('pinrig-manager',),
}


def run(*args):
    subprocess.run(args, check=True, timeout=300)


def install_wheels(venv: Path, bundle: Path, package: str, runner, *, as_service_user: bool = False) -> None:
    """Install only from the local wheelhouse, ignoring the host's pip settings."""
    command = ('env', 'PIP_CONFIG_FILE=/dev/null', str(venv / 'bin/pip'), '--isolated',
               'install', '--no-cache-dir', '--no-index', '--only-binary=:all:', '--find-links', str(bundle / 'wheels'))
    if as_service_user:
        runner('runuser', '-u', 'pinrigdisplay', '--', *command, package)
    else:
        runner(*command, '--upgrade', '--force-reinstall', package)


def check_listener(bind: str, port: int) -> None:
    """Probe with the same IPv4 bind and address reuse as the HTTP service."""
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind, port))


def listener_owners(port: int, *, proc: Path = Path('/proc')) -> set[str]:
    """Resolve listening PIDs to system service units, retaining unknown owners."""
    output = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'],
                                     text=True, timeout=5)
    owners = set()
    for line in output.splitlines():
        pids = re.findall(r'\bpid=(\d+)\b', line)
        if not pids:
            owners.add('unidentified listener')
        for pid in pids:
            try:
                cgroup = (proc / pid / 'cgroup').read_text()
            except OSError:
                cgroup = ''
            unit = re.search(r'(?m)^\d+:[^:\n]*:/system\.slice/(?:[^/\n]+\.slice/)*'
                             r'([^/\n]+\.service)(?:/|$)', cgroup)
            owners.add(unit[1] if unit else f'PID {pid}')
    return owners


def prepare_listener(unit: str, bind: str, port: int, runner) -> None:
    """Reclaim a conflicting listener only if every owner is a known predecessor."""
    try:
        check_listener(bind, port)
        return
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise OSError(f'{unit} cannot bind to {bind}:{port}: {error}') from error

    try:
        owners = listener_owners(port)
    except (OSError, subprocess.SubprocessError) as error:
        raise OSError(f'{unit} cannot bind to {bind}:{port}; could not identify the listener with ss: {error}') from error
    families = '|'.join(re.escape(name) for name in SERVICE_FAMILIES[unit])
    service = re.compile(rf'(?:{families})(?:[-@](?:[A-Za-z0-9_.@-]|\\x[0-9a-fA-F]{{2}})+)?\.service')
    if not owners or any(not service.fullmatch(owner) for owner in owners):
        who = ', '.join(sorted(owners)) or 'unidentified listener'
        raise OSError(f'{unit} cannot bind to {bind}:{port}; port is in use by {who}. '
                      'Free the port or configure a different one.')
    for owner in sorted(owners):
        print(f'Stopping {owner} to free {bind}:{port} for {unit}.', flush=True)
        runner('systemctl', 'stop', owner)
        if owner != unit:
            runner('systemctl', 'disable', owner)
    try:
        check_listener(bind, port)
    except OSError as error:
        raise OSError(f'{unit} still cannot bind to {bind}:{port} after stopping '
                      f'{", ".join(sorted(owners))}: {error}') from error


def get_json(url: str) -> dict:
    # These are host-local service checks, even when the listener uses a LAN IP.
    with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
        value = json.loads(response.read(1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    return value


def verify_service(role: str, config: dict, release: str, *, get=get_json, clock=time.monotonic, delay=time.sleep) -> None:
    """Wait for the installed process to report its exact software release."""
    bind = config.get('bind', '127.0.0.1')
    if bind in ('0.0.0.0', '::'):
        bind = '127.0.0.1'
    port = config.get('port', 48194 if role == 'rig' else 48195)
    url = f'http://{bind}:{port}/api/status'
    expected_rig = config['id'] if role == 'rig' else None
    expected = f'release {release!r}'
    if expected_rig is not None:
        expected += f', rig {expected_rig!r}'
    deadline = clock() + 30
    problem = 'no response'
    while clock() < deadline:
        try:
            status = get(url)
            reported_release = status.get('software_release')
            reported_rig = status.get('rig')
            if reported_release == release and (expected_rig is None or reported_rig == expected_rig):
                return
            problem = f'reported release {reported_release!r}'
            if expected_rig is not None:
                problem += f', rig {reported_rig!r}'
        except (OSError, ValueError) as error:
            problem = str(error)
        delay(.5)
    raise OSError(f'{url} never confirmed {expected} ({problem}). '
                  f'Run sudo journalctl -u pinrig-{role} -b -n 80 --no-pager')


def validate_config(config: dict) -> str:
    """Validate configuration before any accounts, files or services change."""
    if not isinstance(config, dict):
        raise ValueError('configuration must be an object')
    role = config.get('role', 'rig')
    if role not in SOFTWARE_ROLES:
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
    if role == 'stream' and 'twitch_client_id' in config:
        client_id = config['twitch_client_id']
        if not isinstance(client_id, str) or (client_id and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', client_id)):
            raise ValueError('invalid Twitch client ID')
    return role


def write_release_metadata(path: Path, text: str) -> None:
    """Never follow a service-created link when writing privileged metadata."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(text)


def verify_manager(config: dict, *, get=get_json, clock=time.monotonic, delay=time.sleep) -> None:
    """Verify the independent management API."""
    bind = config.get('management_bind', config.get('bind', '0.0.0.0'))
    if bind == '0.0.0.0':
        bind = '127.0.0.1'
    url = 'http://%s:%s/api/health' % (bind, config.get('management_port', 48198))
    deadline = clock() + 30
    while clock() < deadline:
        try:
            if get(url).get('management_schema') == 1:
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
                                   if not key.endswith('_token')}))
    settings.chmod(0o600)
    unit = root / 'etc/systemd/system/pinrig-manager.service'
    if unit.exists():
        runner('systemctl', 'stop', 'pinrig-manager.service')
    bind = config.get('management_bind', config.get('bind', '0.0.0.0'))
    port = config.get('management_port', 48198)
    prepare_listener('pinrig-manager.service', bind, port, runner)
    runner(sys.executable, '-m', 'venv', str(base))
    install_wheels(base, bundle, 'pinrig-rig', runner)
    state = root / 'var/lib/pinrig-manager'
    state.mkdir(parents=True, exist_ok=True, mode=0o755)
    unit.write_text('[Unit]\nDescription=Pinrig software management API\nAfter=network.target\n'
        '[Service]\nUser=root\n'
        'ExecStart=' + str(base / 'bin/pinrig-manager') + ' --bind ' + bind +
        ' --port ' + str(port) + '\nRestart=on-failure\nRestartSec=3\n'
        'TimeoutStopSec=660\nUMask=0022\n[Install]\nWantedBy=multi-user.target\n')
    runner('systemctl', 'daemon-reload')
    runner('systemctl', 'enable', '--now', 'pinrig-manager.service')
    verify(config)


def install(bundle: Path, config: dict, *, root: Path = Path('/'), runner=run, verify=verify_service, management: bool = True) -> None:
    if os.geteuid() != 0:
        raise ValueError('run installer with sudo')
    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11+ required')
    role = validate_config(config)
    manifest = validate_software(bundle, role=role)
    release = manifest['release']
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
        install_wheels(target, bundle, 'pinrig-' + role, runner, as_service_user=True)
        write_release_metadata(marker, fingerprint)
    # Mark the exact deployed bundle separately from Python package versions.
    write_release_metadata(target / 'release.json', json.dumps({'release': release}))
    state = root / ('var/lib/pinrig-' + role)
    state.mkdir(parents=True, exist_ok=True)
    (state / 'releases').mkdir(exist_ok=True)
    os.chown(state, account.pw_uid, account.pw_gid)
    os.chown(state / 'releases', account.pw_uid, account.pw_gid, follow_symlinks=False)
    env = root / ('etc/pinrig-' + role + '.env')
    if env.is_symlink():
        raise ValueError('environment file must not be a symlink')
    if not env.exists():
        env.touch(mode=0o600, exist_ok=False)
    else:
        previous = env.read_text()
        retired = {'PINRIG_OBS_TOKEN', 'PINRIG_MAINTENANCE_TOKEN'}
        current = ''.join(line for line in previous.splitlines(keepends=True)
                          if line.partition('=')[0].strip() not in retired)
        if current != previous:
            with TemporaryDirectory(dir=env.parent) as temporary:
                replacement = Path(temporary) / env.name
                replacement.touch(mode=0o600)
                replacement.write_text(current)
                replacement.replace(env)
    bind = config.get('bind', '0.0.0.0' if role == 'rig' else '127.0.0.1')
    port = config.get('port', 48194 if role == 'rig' else 48195)
    if role == 'rig':
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', config['id']):
            raise ValueError('invalid rig identity')
        serial = config['serial']
        if not serial.startswith('/dev/') or not re.fullmatch(r'[/A-Za-z0-9_.:-]+', serial):
            raise ValueError('select an actual /dev/serial/by-id device')
        runner('usermod', '-a', '-G', 'dialout', 'pinrigdisplay')
        args = ['--rig', config['id'], '--serial', serial, '--bind', bind,
                '--videonode-url', config.get('videonode_url', 'http://127.0.0.1:8090'), '--port', str(port)]
        if config.get('bootsel_mount'):
            args += ['--bootsel-mount', config['bootsel_mount']]
        entry = 'pinrig-rig'
    else:
        settings = state / 'config.json'
        runtime_config = {'rigs': config['rigs'], 'obs_url': config.get('obs_url', 'ws://127.0.0.1:4455')}
        if config.get('twitch_client_id'):
            runtime_config['twitch_client_id'] = config['twitch_client_id']
        write_release_metadata(settings, json.dumps(runtime_config))
        os.chown(settings, account.pw_uid, account.pw_gid, follow_symlinks=False)
        args = ['--config', str(settings), '--bind', bind, '--port', str(port)]
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
        prepare_listener(unit + '.service', bind, port, runner)
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
