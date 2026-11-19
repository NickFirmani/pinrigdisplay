"""Verify release assembly and the standalone bootstrap contract."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shared.release_manifests.display import validate_release
from shared.release_manifests.software import validate_software
from tools.build_release import build as build_display
from tools.build_software_release import build as build_software


ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_display_bundle_contains_the_shared_layout_and_validator(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            runtime = folder / 'fixture.uf2'
            runtime.write_bytes(b'UF2 fixture for bundle assembly only')
            output = folder / 'display'
            build_display(output, 'test-display', runtime, '1.29.0')
            manifest = validate_release(output)
            self.assertEqual(manifest['release'], 'test-display')
            self.assertEqual((output / 'runtime.uf2').read_bytes(), runtime.read_bytes())
            for bundled_file, source in [
                ('commands.py', 'shared/display_contracts/commands.py'),
                ('layout.py', 'shared/artwork/layout.py'),
            ]:
                self.assertEqual((output / bundled_file).read_bytes(), (ROOT / source).read_bytes())

    def test_role_selects_the_wheel_sources_and_standalone_bootstrap(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            for role in ('rig', 'stream'):
                with self.subTest(role=role):
                    output = folder / role

                    def wheel(args, *, check):
                        self.assertTrue(check)
                        self.assertEqual(args[-2:], [str(ROOT / 'shared'), str(ROOT / role)])
                        (output / 'wheels' / f'{role}-fixture.whl').write_bytes(b'wheel fixture')

                    with patch('tools.build_software_release.subprocess.run', side_effect=wheel):
                        build_software(output, f'test-{role}', role)

                    manifest = validate_software(output, role=role)
                    self.assertEqual(manifest['role'], role)
                    with self.assertRaisesRegex(ValueError, 'invalid software manifest'):
                        validate_software(output, role='stream' if role == 'rig' else 'rig')

                    # The installer must load with only stdlib from outside the repo.
                    script = (
                        'import json, runpy, sys; from pathlib import Path; '
                        'bundle = Path(sys.argv[1]); '
                        'bootstrap = runpy.run_path(str(bundle / "install_linux.py")); '
                        'print(json.dumps(bootstrap["validate_software"](bundle, role=sys.argv[2])))'
                    )
                    result = subprocess.run([sys.executable, '-I', '-S', '-c', script,
                                             os.fspath(output), role],
                                            cwd=folder, capture_output=True, check=True, text=True)
                    self.assertEqual(json.loads(result.stdout), manifest)
