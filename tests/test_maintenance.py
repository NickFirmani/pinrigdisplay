"""Release, maintenance and remote-status contracts without hardware or sleeps."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pinrig_host.client import LocalClient
from pinrig_host.delivery import LocalDelivery
from pinrig_host.service import Host
from pinrig_producers.authority import Authority
from pinrig_producers.maintenance import FirmwareInstaller, Jobs
from pinrig_producers.overview import Status, load_config
from pinrig_producers.releases import REQUIRED, REQUIRED_ASSETS, validate_release
from pinrig_producers.deployment import deployment_action
from tests.helpers import device


def bundle(path):
    identity = {'release': 'test-1', 'target': 'pico2w', 'protocol': 1, 'runtime': '1.0.0'}
    for name in REQUIRED | REQUIRED_ASSETS | {'runtime.uf2'}:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(identity) if name == 'identity.json' else 'test')
    manifest = {'schema': 1, **identity, 'files': {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}}
    (path / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


class ReleaseTests(unittest.TestCase):
    def test_release_requires_complete_matching_payload(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)
            manifest = bundle(path)
            self.assertEqual(validate_release(path)['release'], 'test-1')
            (path / 'main.py').write_text('corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                validate_release(path)
            (path / 'main.py').write_text('test')
            del manifest['files']['assets/fonts.json']
            (path / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'missing'):
                validate_release(path)

    def test_traversal_payload_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)
            manifest = bundle(path)
            manifest['files']['../escape'] = 'bad'
            (path / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'invalid release file'):
                validate_release(path)


class MaintenanceTests(unittest.TestCase):
    def host(self):
        controller, clock, _ = device()
        host = Host(LocalDelivery(controller), clock=clock)
        self.addCleanup(host.close)
        self.addCleanup(setattr, controller, 'closed', True)
        return controller, clock, host

    def test_status_ages_and_maintenance_reject_commands(self):
        controller, clock, host = self.host()
        host.tick()
        client = LocalClient(host)
        self.assertFalse(client.send('status', {})['result']['device_status_stale'])
        clock.advance(4)
        self.assertTrue(client.send('status', {})['result']['device_status_stale'])
        host.begin_maintenance()
        self.assertFalse(client.send('set_state', {'state': 'on_air'})['ok'])
        host.tick()
        self.assertIsNone(host.device_session)
        host.end_maintenance()
        host.tick()
        self.assertTrue(client.send('status', {})['result']['connected'])
        authority = Authority('third-rig', client, clock=clock)
        authority.observe_obs(True, 8)
        clock.advance(2)
        self.assertEqual(authority.status()['source_ages']['obs'], 2)
        self.assertTrue(authority.status()['sources']['obs']['fresh'])
        clock.advance(8)
        self.assertFalse(authority.status()['sources']['obs']['fresh'])
        self.assertIsNone(controller.status()['firmware']['release'])

    def test_upload_failure_releases_usb_and_preserves_receipts(self):
        _, _, host = self.host()
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            raise OSError('upload failed')
        with TemporaryDirectory() as temp:
            bundle(Path(temp))
            installer = FirmwareInstaller(host, '/dev/test', run=run)
            with self.assertRaisesRegex(OSError, 'upload failed'):
                installer.install(Path(temp), lambda phase: None)
        self.assertFalse(host.maintenance)
        self.assertFalse(any('interactions.json' in str(arg) for arg in calls[0]))
        host.tick()
        self.assertIsNotNone(host.device_session)

    def test_success_verifies_version_and_entrypoint_is_last(self):
        controller, clock, host = self.host()
        calls = []
        original = controller.status
        def status():
            value = original()
            value['firmware']['release'] = 'test-1'
            value['runtime_version'] = [1, 0, 0]
            return value
        controller.status = status
        with TemporaryDirectory() as temp:
            bundle(Path(temp))
            installer = FirmwareInstaller(host, '/dev/test', run=lambda args, **kw: calls.append(args), clock=clock, delay=clock.advance)
            self.assertEqual(installer.install(Path(temp), lambda p: None)['release'], 'test-1')
        uploads = [c for c in calls if 'cp' in c]
        self.assertEqual(uploads[-1][-1], ':main.py')
        self.assertFalse(any(':runtime.uf2' in c for c in uploads))
        self.assertFalse(host.maintenance)

    def test_verification_timeout_is_failure(self):
        _, clock, host = self.host()
        with TemporaryDirectory() as temp:
            bundle(Path(temp))
            installer = FirmwareInstaller(host, '/dev/test', run=lambda *a, **kw: None, clock=clock, delay=clock.advance)
            with self.assertRaisesRegex(OSError, 'verification timed out'):
                installer.install(Path(temp), lambda p: None)
        self.assertFalse(host.maintenance)

    def test_jobs_reject_overlap_and_recover_after_restart(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'job.json'
            jobs = Jobs(path)
            pending = []
            jobs.start(lambda phase: {'done': True}, launch=pending.append)
            with self.assertRaisesRegex(ValueError, 'already running'):
                jobs.start(lambda p: None)
            restarted = Jobs(path)
            self.assertEqual(restarted.status()['state'], 'failed')
            pending.pop()()
            self.assertEqual(jobs.status()['state'], 'succeeded')
            def fail(phase):
                raise OSError('transport failed')
            jobs.start(fail, launch=lambda work: work())
            self.assertEqual(jobs.status()['error'], 'transport failed')


class OverviewTests(unittest.TestCase):
    def test_independent_polling_stale_and_recovery(self):
        _, clock, _ = device()
        rigs = [{'id': 'a', 'url': 'http://a'}, {'id': 'b', 'url': 'http://b'}]
        status = Status(rigs, clock=clock)
        good = lambda url: {'rig': url.split('/')[2], 'status_schema': 1, 'software_version': 'test'}
        status.poll(rigs[0], get=good)
        status.poll(rigs[1], get=lambda url: (_ for _ in ()).throw(OSError('offline')))
        snapshot = status.snapshot()
        self.assertFalse(snapshot['rigs'][0]['stale'])
        self.assertTrue(snapshot['rigs'][1]['stale'])
        clock.advance(7)
        self.assertTrue(status.snapshot()['rigs'][0]['stale'])
        status.poll(rigs[1], get=good)
        self.assertFalse(status.snapshot()['rigs'][1]['stale'])
        status.poll(rigs[1], get=lambda url: {'rig': 'wrong', 'status_schema': 1})
        self.assertTrue(status.snapshot()['rigs'][1]['stale'])
        self.assertEqual(status.snapshot()['rigs'][1]['status']['rig'], 'b')

    def test_config_multiple_rigs_and_duplicate_validation(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            rigs = [{'id': str(i), 'url': 'http://rig-' + str(i), 'scenes': ['Scene ' + str(i)]} for i in range(3)]
            path.write_text(json.dumps({'rigs': rigs}))
            self.assertEqual(len(load_config(path)['rigs']), 3)
            rigs.append(rigs[0])
            path.write_text(json.dumps({'rigs': rigs}))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                load_config(path)

class DeploymentTests(unittest.TestCase):
    def software(self, path):
        (path / 'wheels').mkdir()
        (path / 'wheels/test.whl').write_text('test wheel')
        (path / 'install_linux.py').write_text('test installer')
        manifest = {'schema': 1, 'protocol': 1, 'target': 'linux', 'release': 'software-1', 'files': {
            name: hashlib.sha256((path / name).read_bytes()).hexdigest()
            for name in ('install_linux.py', 'wheels/test.whl')}}
        (path / 'software.json').write_text(json.dumps(manifest))
        return manifest

    def test_api_deployment_uploads_waits_and_verifies_release(self):
        _, clock, _ = device()
        rig = {'id': 'a', 'url': 'http://a', 'management_url': 'http://a:48198'}
        with TemporaryDirectory() as temp:
            self.software(Path(temp))
            calls = []
            def get(url, **kwargs):
                if '/api/jobs/' in url:
                    calls.append(kwargs)
                    return {'id': 'job-1', 'state': 'succeeded'}
                return {'rig': 'a', 'software_release': 'software-1'}
            action = deployment_action(rig, Path(temp), token='secret',
                upload=lambda url, directory, **kwargs: {'release': 'software-1'},
                post=lambda url, value, **kwargs: {'id': 'job-1'}, get=get,
                clock=clock, delay=clock.advance)
            self.assertEqual(action(lambda p: None)['release'], 'software-1')
            self.assertEqual(calls, [{'headers': {'Authorization': 'Bearer secret'}}])

    def test_api_failure_does_not_report_success(self):
        rig = {'id': 'a', 'url': 'http://a', 'management_url': 'http://a:48198'}
        with TemporaryDirectory() as temp:
            self.software(Path(temp))
            action = deployment_action(rig, Path(temp), token='secret',
                upload=lambda *a, **kw: {'release': 'software-1'},
                post=lambda *a, **kw: {'id': 'job-1'},
                get=lambda *a, **kw: {'id': 'job-1', 'state': 'failed', 'error': 'firmware maintenance busy'})
            with self.assertRaisesRegex(OSError, 'firmware maintenance busy'):
                action(lambda p: None)

    def test_api_requires_explicit_endpoint_and_credential(self):
        with TemporaryDirectory() as temp:
            self.software(Path(temp))
            for rig, token in (({'id': 'a', 'url': 'http://a'}, 'secret'),
                               ({'id': 'a', 'url': 'http://a', 'management_url': 'http://a:48198'}, '')):
                with self.assertRaises(ValueError):
                    deployment_action(rig, Path(temp), token=token)

    def test_linux_install_rerun_preserves_configuration_and_receipts(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.install_linux import install
        with TemporaryDirectory() as temp:
            root = Path(temp) / 'root'
            bundle = Path(temp) / 'bundle'
            bundle.mkdir()
            self.software(bundle)
            (root / 'etc/systemd/system').mkdir(parents=True)
            calls = []
            def runner(*args):
                calls.append(args)
                if 'venv' in args:
                    Path(args[-1]).mkdir(parents=True, exist_ok=True)
            config = {'id': 'a', 'serial': '/dev/test', 'obs_token': 'a' * 32, 'maintenance_token': 'b' * 32}
            with patch('tools.install_linux.os.geteuid', return_value=0), patch('tools.install_linux.os.chown') as ownership, patch('tools.install_linux.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=100, pw_gid=100)):
                install(bundle, config, root=root, runner=runner, verify=lambda *a: None, management=False)
                receipt = root / 'var/lib/pinrig-host/interactions.sqlite3'
                receipt.write_text('durable receipt')
                env = root / 'etc/pinrig-rig.env'
                original = env.read_text()
                install(bundle, {**config, 'obs_token': 'c' * 32}, root=root, runner=runner, verify=lambda *a: None, management=False)
                self.assertEqual(receipt.read_text(), 'durable receipt')
                self.assertEqual(env.read_text(), original)
                ownership.assert_any_call(receipt, 100, 100, follow_symlinks=False)
                self.assertEqual(sum('venv' in call for call in calls), 1)
                package_calls = [call for call in calls if 'venv' in call or any(str(arg).endswith('/bin/pip') for arg in call)]
                self.assertTrue(all(call[:4] == ('runuser', '-u', 'pinrigdisplay', '--') for call in package_calls))
                self.assertFalse(any('useradd' in call for call in calls))
                self.assertTrue((root / 'opt/pinrig-rig/current').is_symlink())


class MaintenanceHTTPTests(unittest.TestCase):
    def request(self, handler, path, value=None, headers=None):
        from tests.test_integrations import FakeConnection
        payload = b'' if value is None else json.dumps(value).encode()
        method = 'GET' if value is None else 'POST'
        fields = {'Host': 'rig:48194', 'Content-Type': 'application/json', 'Content-Length': str(len(payload)), **(headers or {})}
        raw = (f'{method} {path} HTTP/1.0\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode() + payload
        connection = FakeConnection(raw)
        handler(connection, ('127.0.0.1', 0), object())
        header, body = connection.output.getvalue().split(b'\r\n\r\n', 1)
        return int(header.split()[1]), body

    def test_firmware_endpoint_authorization_and_path_validation(self):
        from pinrig_producers.rig import make_rig_handler
        from tests.test_integrations import Client
        with TemporaryDirectory() as temp:
            path = Path(temp)
            maintenance = {'jobs': Jobs(path / 'job.json'), 'releases': path, 'installer': None}
            authority = Authority('rig1', Client())
            handler = make_rig_handler(authority, maintenance=maintenance, maintenance_token='secret')
            value = {'release': 'valid', 'clean': False}
            self.assertEqual(self.request(handler, '/api/firmware', value)[0], 403)
            self.assertEqual(self.request(handler, '/api/firmware', value, {'Authorization': 'Bearer secret', 'Origin': 'http://evil'})[0], 403)
            self.assertEqual(self.request(handler, '/api/firmware', {'release': '..', 'clean': False}, {'Authorization': 'Bearer secret'})[0], 422)
            self.assertEqual(self.request(handler, '/api/maintenance')[0], 200)

    def test_overview_routes_and_rejected_installs(self):
        from pinrig_producers.overview import handler
        with TemporaryDirectory() as temp:
            status = Status([{'id': 'a', 'url': 'http://a'}])
            handle = handler(status, Jobs(Path(temp) / 'jobs.json'), lambda rig, release: lambda phase: {}, 'secret')
            self.assertIn(b'Stream overview', self.request(handle, '/')[1])
            self.assertEqual(self.request(handle, '/api/install', {'rig': 'a', 'release': 'v1'})[0], 403)
            self.assertEqual(self.request(handle, '/api/install', {'rig': 'wrong', 'release': 'v1'}, {'Authorization': 'Bearer secret'})[0], 422)
            self.assertEqual(self.request(handle, '/api/status')[0], 200)

class OBSDiagnosticsTests(unittest.TestCase):
    def test_custom_scene_mapping_and_independent_delivery_reports(self):
        from pinrig_producers.obs import run
        from tests.test_integrations import FakeOBS
        class Stop:
            stopped = False
            def is_set(self): return self.stopped
            def wait(self, duration): self.stopped = True
        socket = FakeOBS(scene='Third')
        socket.close = lambda: None
        rigs = [{'id': name, 'url': 'http://' + name} for name in ('a', 'b', 'c')]
        status = Status(rigs)
        calls = []
        def post(url, value, **kwargs):
            calls.append(value)
            if value['rig'] == 'b':
                raise OSError('unreachable')
        run({r['id']: r['url'] for r in rigs}, Stop(), connect=lambda *a, **k: socket,
            post=post, status=status, mappings={'a': ['First'], 'b': ['Second'], 'c': ['Third']})
        self.assertEqual({v['rig']: v['live'] for v in calls}, {'a': False, 'b': False, 'c': True})
        report = status.snapshot()
        self.assertEqual(report['obs']['scene'], 'Third')
        self.assertTrue(report['obs']['streaming'])
        self.assertFalse(report['obs']['stale'])
        self.assertEqual(report['rigs'][1]['delivery']['error'], 'unreachable')
        self.assertIsNone(report['rigs'][2]['delivery']['error'])

    def test_failed_obs_attempt_does_not_refresh_last_good_observation(self):
        _, clock, _ = device()
        status = Status([], clock=clock)
        status.observed({'connected': True, 'scene': 'First'})
        clock.advance(12)
        status.observed({'connected': False, 'error': 'authentication rejected'})
        self.assertEqual(status.snapshot()['obs']['age'], 12)
        self.assertTrue(status.snapshot()['obs']['stale'])


class InstallLockTests(unittest.TestCase):
    def test_independent_jobs_cannot_overlap_installation(self):
        from pinrig_producers.maintenance import installation_lock
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'installation.lock'
            with installation_lock(path):
                with self.assertRaisesRegex(ValueError, 'another installation'):
                    with installation_lock(path):
                        self.fail('second installer acquired active lock')
            with installation_lock(path):
                pass

    def test_runtime_install_requires_explicit_mount_and_releases_usb(self):
        controller, clock, _ = device()
        host = Host(LocalDelivery(controller), clock=clock)
        self.addCleanup(host.close)
        with TemporaryDirectory() as temp:
            bundle(Path(temp))
            installer = FirmwareInstaller(host, '/dev/test')
            with self.assertRaisesRegex(ValueError, 'bootsel-mount'):
                installer.install(Path(temp), lambda p: None, runtime=True)
        self.assertFalse(host.maintenance)

    def test_installer_rejects_invalid_configuration_before_changes(self):
        from tools.install_linux import validate_config
        for config in ({'id': 'a', 'serial': '/dev/test', 'port': -1}, {'id': 'a', 'serial': '/dev/test', 'bind': 'bad;command'}, {'id': 'a', 'serial': '/tmp/device'}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)

class ServiceVerificationTests(unittest.TestCase):
    def test_retry_until_correct_release_and_rig(self):
        from tools.install_linux import verify_service
        _, clock, _ = device()
        values = iter([{'software_release': 'old', 'rig': 'a'}, {'software_release': 'new', 'rig': 'wrong'}, {'software_release': 'new', 'rig': 'a'}])
        verify_service('rig', {'id': 'a'}, 'new', get=lambda url: next(values), clock=clock, delay=clock.advance)
        self.assertEqual(clock(), 1)

    def test_startup_failure_does_not_report_success(self):
        from tools.install_linux import verify_service
        _, clock, _ = device()
        def get(url):
            raise OSError('service crashed')
        with self.assertRaisesRegex(OSError, 'inspect journalctl'):
            verify_service('rig', {'id': 'a'}, 'new', get=get, clock=clock, delay=clock.advance)

class CachedStatusTests(unittest.TestCase):
    def test_polling_status_during_usb_work_does_not_report_sender_busy(self):
        controller, clock, _ = device()
        host = Host(LocalDelivery(controller), clock=clock)
        self.addCleanup(host.close)
        host.tick()
        authority = Authority('rig1', LocalClient(host), clock=clock)
        with host.lock, authority.sender_lock:
            status = authority.status()['host']
            self.assertTrue(status['ok'])
            self.assertTrue(status['result']['connected'])
            clock.advance(4)
            self.assertTrue(authority.status()['host']['result']['device_status_stale'])
            self.assertFalse(LocalClient(host).send('set_state', {'state': 'on_air'})['ok'])

class InstallerErrorTests(unittest.TestCase):
    def test_firmware_tool_error_is_actionable_and_releases_usb(self):
        import subprocess
        controller, clock, _ = device()
        host = Host(LocalDelivery(controller), clock=clock)
        self.addCleanup(host.close)
        def run(args, **kwargs):
            raise subprocess.CalledProcessError(1, args, stderr=b'Permission denied')
        with TemporaryDirectory() as temp:
            bundle(Path(temp))
            installer = FirmwareInstaller(host, '/dev/test', run=run)
            with self.assertRaisesRegex(OSError, 'USB.*Permission denied'):
                installer.install(Path(temp), lambda p: None)
        self.assertFalse(host.maintenance)
