"""Conversion from Pillow images to ST7796-compatible RGB565 frames."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        expected = self.width * self.height * 2
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")
        if len(self.pixels) != expected:
            raise ValueError(f"frame requires {expected} bytes, got {len(self.pixels)}")


def encode_rgb565(image: Image.Image) -> Frame:
    """Encode a Pillow image as big-endian RGB565 pixel data."""
    rgb = image.convert("RGB")
    source = rgb.tobytes()
    output = bytearray(rgb.width * rgb.height * 2)
    destination = 0

    for position in range(0, len(source), 3):
        red, green, blue = source[position:position + 3]
        value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        output[destination] = value >> 8
        output[destination + 1] = value & 0xFF
        destination += 2

    return Frame(rgb.width, rgb.height, bytes(output))
