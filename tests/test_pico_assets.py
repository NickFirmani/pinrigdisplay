"""Check that the release contains exactly the artwork the Pico can display."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pinrig_producers.releases import REQUIRED_ASSETS
from tools.build_on_air_motion import build as build_motion
from tools.build_pico_assets import build as build_static


class PicoAssetTests(unittest.TestCase):
    def test_generated_and_required_assets_match_display_layouts(self):
        signs = ('on_air', 'camera_active', 'camera_inactive', 'unknown')
        expected = {f'{state}-{step}-0.r' for state in signs for step in (0, 3)}
        expected.update(f'{state}-motion-{phase}.bin'
                        for state in signs if state != 'unknown' for phase in range(4))
        expected.update(('font22.bin', 'font24.bin', 'fonts.json'))

        with TemporaryDirectory() as directory:
            assets = Path(directory)
            build_static(assets)
            build_motion(assets)
            self.assertEqual({path.name for path in assets.iterdir()}, expected)
        self.assertEqual(REQUIRED_ASSETS, {f'assets/{name}' for name in expected})
