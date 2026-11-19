"""Offline bootstrap and read-only checks for the installed Linux roles."""
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import socket
import subprocess
import tempfile
from urllib.request import ProxyHandler, build_opener

from shared.release_manifests.software import SOFTWARE_ROLES, validate_software
from shared.rig_api import OBS_VALID_FOR
from tools.install_linux import validate_config


def install(role: str, bundle: Path, config: Path, *, run=subprocess.run) -> None:
    """Validate local inputs and stage the verified bundle for the service account."""
    if validate_config(json.loads(config.read_text())) != role:
        raise ValueError(f'configuration must be for the {role} role')
    manifest = validate_software(bundle, role=role)
    # A USB mount or home directory may be inaccessible to pinrigdisplay.
    with tempfile.TemporaryDirectory(prefix='pinrig-install-', dir='/tmp') as directory:
        staged = Path(directory)
        (staged / 'wheels').mkdir()
        for name in (*manifest['files'], 'software.json'):
            target = staged / name
            shutil.copyfile(bundle / name, target)
            target.chmod(0o644)
        validate_software(staged, role=role)
        (staged / 'wheels').chmod(0o755)
        staged.chmod(0o755)
        command = ['python3', '-I', str(staged / 'install_linux.py'), '--bundle',
                   str(staged), '--config', str(config.resolve())]
        if os.geteuid() != 0:
            command.insert(0, 'sudo')
        run(command, check=True)


def unit_properties(unit: str) -> dict[str, str]:
    """Read the systemd state of one service, including a missing service."""
    result = subprocess.run(
        ['systemctl', 'show', '--no-pager',
         '--property=LoadState,ActiveState,UnitFileState,FragmentPath', unit + '.service'],
        check=False, capture_output=True, text=True, timeout=5,
    )
    properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode and properties.get('LoadState') != 'not-found':
        raise OSError(result.stderr.strip() or f'systemctl exited with {result.returncode}')
    if 'LoadState' not in properties:
        raise ValueError(f'systemd did not report the state of {unit}')
    return properties


def service_endpoint(fragment: Path, unit: str) -> str:
    """Find the HTTP listener from the PinRig installer's generated service unit."""
    command = next((line.partition('=')[2] for line in fragment.read_text().splitlines()
                    if line.startswith('ExecStart=')), '')
    if not command:
        raise ValueError(f'missing ExecStart in {fragment}')
    args = shlex.split(command)
    try:
        bind = args[args.index('--bind') + 1]
        port = int(args[args.index('--port') + 1])
    except (ValueError, IndexError) as error:
        raise ValueError(f'missing or invalid --bind/--port in {fragment}') from error
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(bind, bind)
    address = f'[{host}]' if ':' in host else host
    path = 'health' if unit == 'pinrig-manager' else 'status'
    return f'http://{address}:{port}/api/{path}'


def get_status(url: str) -> dict:
    """Read the service directly even if the host has a proxy configured."""
    with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
        data = json.loads(response.read(1024 * 1024))
    if not isinstance(data, dict):
        raise ValueError('expected a JSON object')
    return data


def integration_checks(role: str, data: dict, *, out=print) -> list[str]:
    """Summarize and verify the live dependencies reported by a service."""
    if role == 'rig':
        host = data.get('host') or {}
        device = host.get('device') or {}
        firmware = device.get('firmware') or {}
        ready = (host.get('connected') is True and host.get('device_status_stale') is False
                 and device.get('healthy') is True)
        out(f"Pico: {'healthy' if ready else 'unhealthy or unavailable'}, "
            f"firmware {firmware.get('release') or 'unknown'}, "
            f"display {device.get('displayed_state') or 'unknown'}")
        fault = device.get('display_fault') or host.get('delivery_fault')
        if fault:
            out(f'Pico fault: {fault}')
        return [] if ready else ['Pico is disconnected, stale, or reports a display fault']

    obs = data.get('obs') or {}
    obs_ready = obs.get('connected') is True and obs.get('stale') is False
    out(f"OBS: {'connected' if obs_ready else 'stale or disconnected'}")
    if obs.get('error'):
        out(f"OBS error: {obs['error']}")
    errors = [] if obs_ready else ['OBS status is unavailable or stale']
    rigs = data.get('rigs') or []
    if not rigs:
        errors.append('No rigs configured')
    for rig in rigs:
        name = rig['id']
        ready = rig.get('stale') is False and bool(rig.get('status'))
        delivery = rig.get('delivery') or {}
        age = delivery.get('age')
        delivered = isinstance(age, (int, float)) and 0 <= age <= OBS_VALID_FOR and not delivery.get('error')
        out(f"{name}: status {'current' if ready else 'unavailable or stale'}, "
            f"OBS delivery {'successful' if delivered else 'unconfirmed'}")
        if not ready or not delivered:
            errors.append(f"{name}: {rig.get('error') or delivery.get('error') or 'waiting for rig status and OBS delivery'}")
    return errors


def inspect(role: str, *, test: bool, local_only: bool = False, root: Path = Path('/'),
            properties=unit_properties, get=get_status, out=print) -> int:
    """Report local installation status or require its checks to pass."""
    out(f'{socket.gethostname()} | {role} | {platform.machine()} | Python {platform.python_version()}')
    unit = 'pinrig-' + role
    release_file = root / 'opt' / unit / 'current/release.json'
    errors = []
    try:
        release = json.loads(release_file.read_text()).get('release')
    except FileNotFoundError:
        release = None
    except (OSError, ValueError, AttributeError) as error:
        release = None
        errors.append(f'Cannot read installed release: {error}')
    out(f"Installed release: {release or 'none'}")
    if test and not release:
        errors.append('No installed release metadata')

    units = (unit, 'pinrig-manager') if role == 'rig' else (unit,)
    for name in units:
        try:
            info = properties(name)
            load = info['LoadState']
            active = info.get('ActiveState', 'unknown')
            enabled = info.get('UnitFileState') or 'unknown'
            out(f'{name}: {load}, {active}, {enabled}')
            if active != 'active':
                errors.append(f'{name} is not active')
                continue
            url = service_endpoint(Path(info['FragmentPath']), name)
            data = get(url)
            if name == 'pinrig-manager':
                if data.get('management_schema') != 1 or data.get('process') != 'running':
                    raise ValueError('unexpected management health response')
                out(f'Manager health: running ({url})')
                continue
            if data.get('status_schema') != 1 or (role == 'rig' and not data.get('rig')):
                raise ValueError('unexpected service status response')
            running = data.get('software_release')
            out(f"Running release: {running or 'unknown'} ({url})")
            if not release or running != release:
                errors.append(f'{name} is not running the installed release')
            if not local_only:
                errors.extend(integration_checks(role, data, out=out))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
            errors.append(f'{name}: {error}')

    for error in errors:
        out(f"{'FAIL' if test else 'Note'}: {error}")
    if test and not errors:
        out('PASS: local installation' if local_only else 'PASS: installation and connected dependencies')
    return int(test and bool(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=SOFTWARE_ROLES)
    commands = parser.add_subparsers(dest='action', required=True)
    bootstrap = commands.add_parser('install', help='install a prepared offline bundle')
    bootstrap.add_argument('bundle', type=Path, help='directory containing software.json and wheels/')
    bootstrap.add_argument('config', type=Path, help='private role configuration JSON')
    commands.add_parser('status', help='display service, release, and dependency status')
    smoke = commands.add_parser('test', help='check the running installation')
    smoke.add_argument('--local-only', action='store_true', help='allow external dependencies to be disconnected')
    args = parser.parse_args()
    try:
        if args.action == 'install':
            if platform.system() != 'Linux':
                raise ValueError('run the Linux installer on the target host')
            install(args.role, args.bundle, args.config)
        else:
            raise SystemExit(inspect(args.role, test=args.action == 'test',
                                     local_only=getattr(args, 'local_only', False)))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{args.role} {args.action}: {error}\n')


if __name__ == '__main__':
    main()
