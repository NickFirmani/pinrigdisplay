"""Conversion from Pillow images to ST7796-compatible RGB565 frames."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops


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
    red, green, blue = image.convert("RGB").split()
    # Point tables and channel addition execute in Pillow, avoiding a Python
    # iteration per pixel. The terms occupy disjoint bits, so addition is exact.
    high = ImageChops.add(red.point([v & 0xF8 for v in range(256)]),
                         green.point([v >> 5 for v in range(256)]))
    low = ImageChops.add(green.point([(v & 0x1C) << 3 for v in range(256)]),
                        blue.point([v >> 3 for v in range(256)]))
    return Frame(image.width, image.height, Image.merge("LA", (high, low)).tobytes())
