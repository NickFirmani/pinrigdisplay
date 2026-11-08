"""Rig management API: bounded uploads and fixed local software installation."""
from io import BytesIO
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest

from pinrig_producers.manager import SoftwareInstaller, make_manager_handler, stage_release
from pinrig_producers.maintenance import Jobs
from tests import test_maintenance as fixtures
from tests.test_integrations import FakeConnection


def archive(directory: Path) -> bytes:
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as output:
        for path in directory.rglob('*'):
            if path.is_file():
                output.add(path, arcname=path.relative_to(directory).as_posix())
    return stream.getvalue()


class ManagerTests(unittest.TestCase):
    def test_stage_validates_manifest_and_is_immutable(self):
        with TemporaryDirectory() as temp:
            source, target = Path(temp) / 'source', Path(temp) / 'catalog'
            source.mkdir()
            fixtures.DeploymentTests().software(source)
            data = archive(source)
            self.assertEqual(stage_release(BytesIO(data), len(data), target, 'software-1'), {'release': 'software-1'})
            self.assertEqual(stage_release(BytesIO(data), len(data), target, 'software-1'), {'release': 'software-1'})
            (source / 'wheels/test.whl').write_text('damaged')
            damaged = archive(source)
            with self.assertRaisesRegex(ValueError, 'invalid software payload'):
                stage_release(BytesIO(damaged), len(damaged), target, 'software-1')
            self.assertEqual((target / 'software-1/wheels/test.whl').read_text(), 'test wheel')

    def test_archive_links_and_traversal_rejected(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('link', tarfile.SYMTYPE)):
            with self.subTest(name=name), TemporaryDirectory() as temp:
                stream = BytesIO()
                with tarfile.open(fileobj=stream, mode='w') as output:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = '/etc/passwd'
                    output.addfile(member)
                data = stream.getvalue()
                with self.assertRaisesRegex(ValueError, 'regular relative'):
                    stage_release(BytesIO(data), len(data), Path(temp), 'software-1')
                self.assertFalse((Path(temp) / 'software-1').exists())

    def test_installer_uses_fixed_helper_and_config_never_uploaded_script(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp) / 'software-1'
            directory.mkdir()
            fixtures.DeploymentTests().software(directory)
            calls = []
            installer = SoftwareInstaller(Path(temp), Path('/trusted/install_linux.py'), Path('/etc/pinrig-rig.json'),
                run=lambda args, **kwargs: calls.append(args))
            self.assertEqual(installer.install('software-1', lambda phase: None), {'release': 'software-1'})
            self.assertEqual(calls[0][1], '/trusted/install_linux.py')
            self.assertIn('--application-only', calls[0])
            self.assertNotIn(str(directory / 'install_linux.py'), calls[0])
            for invalid in ('../escape', 'current', '/tmp/escape'):
                with self.assertRaises(ValueError):
                    installer.install(invalid, lambda phase: None)

    def request(self, handler, method, path, body=b'', *, token='secret', content_type='application/json', origin=None):
        fields = {'Host': 'rig:48198', 'Content-Type': content_type, 'Content-Length': str(len(body))}
        if token:
            fields['Authorization'] = 'Bearer ' + token
        if origin:
            fields['Origin'] = origin
        raw = (method + ' ' + path + ' HTTP/1.0\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in fields.items()) + '\r\n').encode() + body
        connection = FakeConnection(raw)
        handler(connection, ('127.0.0.1', 0), object())
        header, body = connection.output.getvalue().split(b'\r\n\r\n', 1)
        return int(header.split()[1]), json.loads(body)

    def test_api_upload_install_and_poll_with_authentication(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            fixtures.DeploymentTests().software(source)
            installer = SoftwareInstaller(root / 'catalog', Path('/trusted/helper'), Path('/trusted/config'), run=lambda *a, **kw: None)
            jobs = Jobs(root / 'job.json')
            handler = make_manager_handler(jobs, installer, 'secret')
            data = archive(source)
            self.assertEqual(self.request(handler, 'PUT', '/api/releases/software-1', data, token='', content_type='application/x-tar')[0], 403)
            self.assertEqual(self.request(handler, 'PUT', '/api/releases/software-1', data, content_type='application/x-tar', origin='http://evil')[0], 403)
            self.assertEqual(self.request(handler, 'PUT', '/api/releases/software-1', data, content_type='application/x-tar')[0], 200)
            code, job = self.request(handler, 'POST', '/api/install', json.dumps({'release': 'software-1'}).encode())
            self.assertEqual(code, 202)
            jobs.wait()
            code, result = self.request(handler, 'GET', '/api/jobs/' + job['id'])
            self.assertEqual(code, 200)
            self.assertEqual(result['state'], 'succeeded')
            self.assertEqual(self.request(handler, 'GET', '/api/maintenance')[1]['id'], job['id'])
            self.assertEqual(self.request(handler, 'GET', '/api/health')[1]['management_schema'], 1)
            self.assertEqual(self.request(handler, 'GET', '/api/health', token='')[0], 403)
            self.assertEqual(self.request(handler, 'GET', '/api/jobs/unknown')[0], 404)
            self.assertEqual(self.request(handler, 'POST', '/api/install', b'{"release":"../escape"}')[0], 422)

class BootstrapTests(unittest.TestCase):
    def test_bootstrap_keeps_management_code_separate_from_application(self):
        from tools.install_linux import setup_manager
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'etc/systemd/system').mkdir(parents=True)
            calls = []
            (root / 'etc/pinrig-rig.env').write_text('PINRIG_MAINTENANCE_TOKEN=secret\n')
            setup_manager(root / 'bundle', {'id': 'rig1', 'maintenance_token': 'secret', 'obs_token': 'other', 'serial': '/dev/test'},
                          root, lambda *args: calls.append(args), verify=lambda *args: None)
            helper = root / 'usr/local/lib/pinrig/install_linux.py'
            self.assertIn('def install(', helper.read_text())
            config = json.loads((root / 'etc/pinrig-rig.json').read_text())
            self.assertNotIn('maintenance_token', config)
            unit = (root / 'etc/systemd/system/pinrig-manager.service').read_text()
            self.assertIn('/opt/pinrig-manager/bin/pinrig-manager', unit)
            self.assertNotIn('/pinrig-rig/current/', unit)
            self.assertIn('User=root', unit)

    def test_root_metadata_never_follows_application_symlink(self):
        from tools.install_linux import write_release_metadata
        with TemporaryDirectory() as temp:
            target = Path(temp) / 'target'
            target.write_text('preserved')
            link = Path(temp) / 'release.json'
            link.symlink_to(target)
            with self.assertRaises(OSError):
                write_release_metadata(link, 'changed')
            self.assertEqual(target.read_text(), 'preserved')
