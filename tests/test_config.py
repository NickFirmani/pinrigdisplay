from pathlib import Path
import tempfile
import unittest
from display_controller.config import load_config


class ConfigTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config.toml'; p.write_text(content)
            return load_config(p)

    def test_defaults(self):
        c = self.load('')
        self.assertEqual(c.host, '127.0.0.1'); self.assertEqual(c.dc_pin, 24)
        self.assertEqual(c.speed_hz, 20000000)

    def test_invalid(self):
        for content in ['port=70000', 'animation_fps=true', 'wat=1', 'http_enabled=false',
                        'dc_pin=25', 'serial_path="relative"', 'host=12']:
            with self.subTest(content=content), self.assertRaises(ValueError): self.load(content)
