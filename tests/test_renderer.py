from __future__ import annotations

import unittest

from PIL import Image

from display_controller.display.renderer import Frame, encode_rgb565


class RendererTests(unittest.TestCase):
    def test_encodes_primary_colors_as_big_endian_rgb565(self) -> None:
        image = Image.new("RGB", (4, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)])

        frame = encode_rgb565(image)

        self.assertEqual((frame.width, frame.height), (4, 1))
        self.assertEqual(frame.pixels, bytes.fromhex("f80007e0001fffff"))

    def test_frame_rejects_wrong_payload_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires 8 bytes"):
            Frame(2, 2, b"too short")


if __name__ == "__main__":
    unittest.main()
