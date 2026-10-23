from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from display_controller.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_defaults_and_resolves_relative_logo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[pages]\nlogo_path = "logo.png"\n', encoding="utf-8")

            config = load_config(path)

            self.assertEqual(config.server.port, 48193)
            self.assertEqual(config.display.dc_pin, 24)
            self.assertEqual(config.pages.logo_path, path.parent / "logo.png")
            self.assertEqual(config.pages.pulse_seconds, 4.0)

    def test_rejects_invalid_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[server]\nport = 70000\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "port must be between"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
