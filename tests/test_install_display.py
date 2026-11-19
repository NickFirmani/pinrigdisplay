"""Workstation provisioning through the real installer with a simulated Pico."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from rig.server.firmware_install import FirmwareInstaller
from tests.helpers import SerialEndpoint, device
from tests.test_display_host import Stream
from tests.test_maintenance import bundle
from tools.install_display import main


PORT = '/dev/cu.test-pico'


class InstallDisplayTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.release = Path(directory.name)
        self.manifest = bundle(self.release)
        controller, clock, _ = device()
        self.serial = Stream(SerialEndpoint(controller), clock)
        self.open_serial = Mock(return_value=self.serial)
        self.run_command = Mock()
        self.runtime = [1, 0, 0]
        original_status = controller.status

        def status():
            value = original_status()
            value['firmware']['release'] = self.manifest['release']
            value['runtime_version'] = self.runtime
            return value

        controller.status = status
        self.enterContext(patch.dict(sys.modules, {'serial': SimpleNamespace(Serial=self.open_serial)}))
        self.enterContext(patch.object(Path, 'is_char_device', return_value=True))
        self.enterContext(patch('tools.install_display.FirmwareInstaller',
                                side_effect=lambda host, port: FirmwareInstaller(
                                    host, port, run=self.run_command, clock=clock, delay=clock.advance)))
        self.stdout = self.enterContext(redirect_stdout(StringIO()))
        self.stderr = self.enterContext(redirect_stderr(StringIO()))

    def install(self, port=PORT):
        main(['--bundle', str(self.release), '--port', port])

    def test_uploads_only_listed_app_files_and_verifies_over_usb(self):
        self.install()
        commands = [call.args[0] for call in self.run_command.call_args_list]
        self.assertTrue(all(cmd[:5] == [sys.executable, '-m', 'mpremote', 'connect', PORT]
                            for cmd in commands))
        uploaded = [cmd[-1] for cmd in commands if cmd[5:7] == ['fs', 'cp']]
        self.assertCountEqual(uploaded, [':' + name for name in self.manifest['files']
                                         if name != 'runtime.uf2'])
        self.assertEqual(uploaded[-1], ':main.py')
        self.assertEqual(commands[-1][-1], 'reset')
        self.open_serial.assert_called_once_with(
            PORT, 115200, timeout=.1, write_timeout=1, exclusive=True)
        self.assertTrue(self.serial.closed)
        self.assertIn('Installed test-1. Display is healthy', self.stdout.getvalue())

    def test_bad_bundle_opens_no_usb_connection(self):
        (self.release / 'main.py').write_text('corrupt')
        with self.assertRaises(SystemExit) as exit_code:
            self.install()
        self.assertEqual(exit_code.exception.code, 1)
        self.assertIn('checksum', self.stderr.getvalue())
        self.run_command.assert_not_called()
        self.open_serial.assert_not_called()

    def test_runtime_mismatch_reports_failure_and_closes_usb(self):
        self.runtime = [1, 0, 1]
        with self.assertRaises(SystemExit) as exit_code:
            self.install()
        self.assertEqual(exit_code.exception.code, 1)
        self.assertIn('runtime version mismatch', self.stderr.getvalue())
        self.assertTrue(self.serial.closed)
        self.assertNotIn('Installed', self.stdout.getvalue())

    def test_rejects_automatic_port_selection(self):
        with self.assertRaises(SystemExit) as exit_code:
            self.install('auto')
        self.assertEqual(exit_code.exception.code, 2)
        self.run_command.assert_not_called()
