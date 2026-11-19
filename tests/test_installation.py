"""Checks for the offline operator commands without systemd or attached hardware."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.configure_installation import generate_config
from tools.install_linux import install_wheels
from tools.installation import inspect, install, main


class InstallationTests(unittest.TestCase):
    def test_install_cli_accepts_release_and_defaults_to_role_config(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            for role in ('rig', 'stream'):
                with self.subTest(role=role):
                    bundle = home / f'{role}-v1'
                    bundle.mkdir()
                    config = home / f'{role}-config.json'
                    config.touch()
                    with (patch.dict(os.environ, {'HOME': str(home)}),
                          patch('tools.installation.platform.system', return_value='Linux'),
                          patch('tools.installation.install') as bootstrap,
                          patch('sys.argv', ['installation.py', role, 'install', 'v1'])):
                        main()
                    bootstrap.assert_called_once_with(role, bundle, config)

    def test_install_cli_accepts_explicit_paths_and_reports_missing_config(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            bundle = home / 'bundle'
            bundle.mkdir()
            config = home / 'custom.json'
            config.touch()
            with (patch.dict(os.environ, {'HOME': str(home)}),
                  patch('tools.installation.platform.system', return_value='Linux'),
                  patch('tools.installation.install') as bootstrap):
                with patch('sys.argv', ['installation.py', 'rig', 'install', str(bundle), str(config)]):
                    main()
                bootstrap.assert_called_once_with('rig', bundle, config)
                with (patch('sys.argv', ['installation.py', 'rig', 'install', str(bundle)]),
                      patch('sys.stdin.isatty', return_value=False),
                      patch('sys.stderr') as stderr, self.assertRaises(SystemExit) as error):
                    main()
                self.assertEqual(error.exception.code, 1)
                self.assertIn(f'configuration file not found: {home / "rig-config.json"}',
                              stderr.write.call_args.args[0])

    def test_interactive_install_generates_stream_config_before_bootstrap(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            bundle = home / 'stream-v1'
            bundle.mkdir()
            config = home / 'stream-config.json'
            answers = ['', '', 'http://rig1.local:48194', '', 'Pinball, Both', 'y',
                       '', 'http://rig2.local:48194', '', '', '']
            with (patch.dict(os.environ, {'HOME': str(home)}),
                  patch('tools.installation.platform.system', return_value='Linux'),
                  patch('tools.installation.install') as bootstrap,
                  patch('sys.argv', ['installation.py', 'stream', 'install', 'v1']),
                  patch('sys.stdin.isatty', return_value=True),
                  patch('builtins.input', side_effect=answers),
                  patch('builtins.print')):
                main()
            bootstrap.assert_called_once_with('stream', bundle, config)
            saved = json.loads(config.read_text())
            self.assertEqual(set(saved), {'role', 'bind', 'obs_url', 'rigs'})
            self.assertEqual(saved['rigs'][0]['management_url'], 'http://rig1.local:48198')
            self.assertEqual(saved['rigs'][0]['scenes'], ['Pinball', 'Both'])
            self.assertEqual(saved['rigs'][1]['id'], 'rig2')
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_guided_rig_config_accepts_explicit_serial(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'rig-config.json'
            with (patch('builtins.input', side_effect=['rig2', 'ttyACM0', '/dev/ttyACM0']),
                  patch('builtins.print')):
                generate_config('rig', config, serial_directory=root / 'serial')
            saved = json.loads(config.read_text())
            self.assertEqual(saved['id'], 'rig2')
            self.assertEqual(saved['serial'], '/dev/ttyACM0')
            self.assertEqual(set(saved), {'role', 'bind', 'id', 'serial'})

    def test_install_stages_only_manifest_files_and_rejects_wrong_role(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'bundle'
            (bundle / 'wheels').mkdir(parents=True)
            installer = bundle / 'install_linux.py'
            installer.write_text('# test bootstrap')
            wheel = bundle / 'wheels' / 'test.whl'
            wheel.write_bytes(b'test wheel')
            (wheel.parent / 'unlisted.whl').touch()
            manifest = {'schema': 1, 'protocol': 1, 'target': 'linux', 'role': 'rig',
                        'release': 'v1', 'files': {path.relative_to(bundle).as_posix():
                            hashlib.sha256(path.read_bytes()).hexdigest() for path in (installer, wheel)}}
            (bundle / 'software.json').write_text(json.dumps(manifest))
            config = root / 'rig.json'
            config.write_text(json.dumps({'id': 'rig1', 'serial': '/dev/ttyACM0'}))
            staged_paths = []

            def run(args, *, check):
                self.assertTrue(check)
                self.assertEqual(args[:3], ['sudo', 'python3', '-I'])
                self.assertEqual(Path(args[-1]), config.resolve())
                staged = Path(args[args.index('--bundle') + 1])
                staged_paths.append(staged)
                self.assertEqual(staged.stat().st_mode & 0o777, 0o755)
                self.assertEqual((staged / 'wheels').stat().st_mode & 0o777, 0o755)
                self.assertEqual((staged / 'wheels/test.whl').stat().st_mode & 0o777, 0o644)
                self.assertEqual([p.name for p in (staged / 'wheels').iterdir()], ['test.whl'])
                self.assertFalse((staged / config.name).exists())

            with patch('tools.installation.os.geteuid', return_value=1000):
                install('rig', bundle, config, run=run)
                with self.assertRaisesRegex(ValueError, 'configuration must be for the stream role'):
                    install('stream', bundle, config, run=run)
                config.write_text(json.dumps({'role': 'stream', 'rigs': [{'id': 'rig1'}]}))
                with self.assertRaisesRegex(ValueError, 'invalid software manifest'):
                    install('stream', bundle, config, run=run)
            self.assertEqual(len(staged_paths), 1)
            self.assertFalse(staged_paths[0].exists())

    def test_offline_pip_ignores_host_configuration(self):
        calls = []
        for as_service_user in (False, True):
            install_wheels(Path('/venv'), Path('/bundle'), 'pinrig-rig',
                           lambda *args: calls.append(args), as_service_user=as_service_user)
        for args in calls:
            index = args.index('/venv/bin/pip')
            self.assertEqual(args[index - 2:index], ('env', 'PIP_CONFIG_FILE=/dev/null'))
            self.assertIn('--isolated', args)
            self.assertIn('--no-index', args)
            self.assertEqual(args[args.index('--find-links') + 1], '/bundle/wheels')

    def test_uninstalled_status_is_readable_and_test_fails(self):
        with TemporaryDirectory() as directory:
            output = []
            missing = lambda unit: {'LoadState': 'not-found', 'ActiveState': 'inactive'}
            args = dict(root=Path(directory), properties=missing, out=output.append)
            self.assertEqual(inspect('rig', test=False, **args), 0)
            self.assertIn('Installed release: none', output)
            self.assertIn('pinrig-manager: not-found, inactive, unknown', output)
            self.assertEqual(inspect('rig', test=True, **args), 1)

    def test_rig_checks_use_configured_ports_and_require_a_healthy_pico(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / 'opt/pinrig-rig/current/release.json'
            release.parent.mkdir(parents=True)
            release.write_text('{"release": "v1"}')
            expected = {
                'http://127.0.0.1:5000/api/status':
                    {'status_schema': 1, 'software_release': 'v1', 'rig': 'rig1'},
                'http://127.0.0.1:5001/api/health':
                    {'management_schema': 1, 'process': 'running'},
            }
            for name, port in (('pinrig-rig', 5000), ('pinrig-manager', 5001)):
                (root / f'{name}.service').write_text(
                    f'[Service]\nExecStart=/bin/{name} --bind 0.0.0.0 --port {port}\n')

            def properties(name):
                return {'LoadState': 'loaded', 'ActiveState': 'active', 'UnitFileState': 'enabled',
                        'FragmentPath': str(root / f'{name}.service')}

            params = dict(root=root, properties=properties, get=expected.__getitem__, out=lambda *_: None)
            self.assertEqual(inspect('rig', test=True, local_only=True, **params), 0)
            self.assertEqual(inspect('rig', test=True, **params), 1)
            rig = expected['http://127.0.0.1:5000/api/status']
            rig['host'] = {'connected': True, 'device_status_stale': False,
                           'device': {'healthy': True, 'firmware': {'release': 'display-v1'}}}
            self.assertEqual(inspect('rig', test=True, **params), 0)
            rig['software_release'] = 'v0'
            self.assertEqual(inspect('rig', test=True, local_only=True, **params), 1)

    def test_stream_test_requires_fresh_obs_delivery_for_every_rig(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / 'opt/pinrig-stream/current/release.json'
            release.parent.mkdir(parents=True)
            release.write_text('{"release": "v1"}')
            fragment = root / 'pinrig-stream.service'
            fragment.write_text('ExecStart=/bin/pinrig-stream --bind 127.0.0.1 --port 48195\n')
            delivery = {'age': 20, 'error': None}
            status = {'status_schema': 1, 'software_release': 'v1',
                      'obs': {'connected': True, 'stale': False},
                      'rigs': [{'id': 'rig1', 'stale': False, 'status': {'rig': 'rig1'},
                                'delivery': delivery}]}
            params = dict(root=root, properties=lambda _: {'LoadState': 'loaded',
                          'ActiveState': 'active', 'FragmentPath': str(fragment)},
                          get=lambda _: status, out=lambda *_: None)
            self.assertEqual(inspect('stream', test=True, local_only=True, **params), 0)
            self.assertEqual(inspect('stream', test=True, **params), 1)
            delivery['age'] = 1
            self.assertEqual(inspect('stream', test=True, **params), 0)
            delivery['error'] = 'HTTP 401'
            self.assertEqual(inspect('stream', test=True, **params), 1)

    def test_role_entrypoints_work_outside_checkout(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            for role in ('rig', 'stream'):
                for action in ('status', 'install', 'test'):
                    with self.subTest(role=role, action=action):
                        script = root / role / 'installation' / f'{action}.sh'
                        result = subprocess.run([script, '--help'], cwd=directory,
                                                check=True, capture_output=True, text=True)
                        self.assertIn(f'{{rig,stream}} {action}', result.stdout)

    def test_source_copy_updates_managed_files_and_preserves_local_files(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            fixture = Path(directory)
            source = fixture / 'source'
            (source / 'tools').mkdir(parents=True)
            script = source / 'tools/copy-source.sh'
            shutil.copy2(root / 'tools/copy-source.sh', script)
            shutil.copy2(root / 'tools/update_source.py', source / 'tools')
            (source / 'README.md').write_text('working tree')
            old_tool = source / 'tools/old.py'
            old_tool.touch()
            (source / '.gitignore').write_text('ignored.py\n')
            (source / 'tools/ignored.py').touch()
            subprocess.run(['git', 'init', '-q'], cwd=source, check=True)
            remote_home = fixture / 'remote-home'
            remote_home.mkdir()
            ssh = fixture / 'ssh'
            ssh.write_text('#!/bin/sh\n[ "$2" = operator@target ] || exit 2\nexec sh -c "$3"\n')
            ssh.chmod(0o755)
            env = {**os.environ, 'PATH': f"{fixture}:{os.environ['PATH']}", 'HOME': str(remote_home)}
            command = [script, 'operator@target', 'pinrig-new']
            subprocess.run(command, cwd=fixture, env=env, check=True)
            destination = remote_home / 'pinrig-new'
            self.assertEqual((destination / 'README.md').read_text(), 'working tree')
            self.assertTrue((destination / 'tools/copy-source.sh').is_file())
            self.assertFalse((destination / 'tools/ignored.py').exists())
            (destination / 'marker').touch()
            (source / 'README.md').write_text('updated working tree')
            old_tool.unlink()
            subprocess.run(command, cwd=fixture, env=env, check=True)
            self.assertEqual((destination / 'README.md').read_text(), 'updated working tree')
            self.assertFalse((destination / 'tools/old.py').exists())
            self.assertTrue((destination / 'marker').exists())

    def test_bundle_scripts_delegate_to_builder_for_role_and_relay_via_workstation(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / 'tools').mkdir()
            shutil.copy2(root / 'tools/build-linux-bundle.sh', fixture / 'tools')
            venv_bin = fixture / '.venv/bin'
            venv_bin.mkdir(parents=True)
            for path, body in ((fixture / 'uname', 'printf "Linux\\n"'),
                               (venv_bin / 'python', 'printf "%s\\n" "$@"'),
                               (fixture / 'scp', 'printf "%s\\n" "$@"')):
                path.write_text(f'#!/bin/sh\n{body}\n')
                path.chmod(0o755)
            env = {**os.environ, 'PATH': f"{fixture}:{os.environ['PATH']}", 'HOME': str(fixture)}
            for role in ('rig', 'stream'):
                build_dir = fixture / role / 'installation'
                build_dir.mkdir(parents=True)
                shutil.copy2(root / role / 'installation/build.sh', build_dir)
                result = subprocess.run([build_dir / 'build.sh', 'v1'], cwd=fixture, env=env,
                                        check=True, capture_output=True, text=True)
                output = fixture / f'{role}-v1'
                self.assertEqual(result.stdout.splitlines(), [
                    '-P', '-m', 'tools.build_software_release', '--role', role,
                    '--release', 'v1', '--output', str(output), f'Bundle ready: {output}',
                ])
            relay = subprocess.run([root / 'tools/copy-bundle.sh', 'builder', 'target', 'rig', 'v1'],
                                   env=env, check=True, capture_output=True, text=True)
            self.assertEqual(relay.stdout.splitlines(), ['-3', '-r', '--', 'builder:rig-v1', 'target:'])
