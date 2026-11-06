from __future__ import annotations

import unittest

from PIL import Image

from pinrig_artwork.renderer import Frame, encode_rgb565


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

class EncoderEquivalenceTests(unittest.TestCase):
    def test_quantization_boundaries_and_channel_combinations(self):
        colors = [(r, g, b) for r in range(256) for g, b in
                  ((0, 0), (255, 255), (r, 255-r), ((r*7)%256, (r*13)%256))]
        image = Image.new('RGB', (len(colors), 1))
        image.putdata(colors)
        expected = b''.join((((r & 248) << 8) | ((g & 252) << 3) | (b >> 3)).to_bytes(2, 'big')
                            for r, g, b in colors)
        self.assertEqual(encode_rgb565(image).pixels, expected)

    def test_non_rgb_input(self):
        image = Image.new('RGBA', (2, 3), (255, 0, 0, 20))
        self.assertEqual(encode_rgb565(image).pixels, bytes.fromhex('f800') * 6)
