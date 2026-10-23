#!/usr/bin/env python3
"""Initialize a 480x320 ST7796 display over SPI and draw "hello".

Wiring uses Raspberry Pi BCM numbering:
  CS=GPIO8/CE0, RESET=GPIO25, DC=GPIO24, MOSI=GPIO10, SCLK=GPIO11.
"""

from __future__ import annotations

import argparse
import time

import RPi.GPIO as GPIO
import spidev
from PIL import Image, ImageDraw, ImageFont


class ST7796:
    WIDTH = 480
    HEIGHT = 320

    def __init__(self, bus: int = 0, device: int = 0, dc: int = 24,
                 reset: int = 25, speed_hz: int = 20_000_000) -> None:
        self.dc = dc
        self.reset = reset
        self.spi = spidev.SpiDev()

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.dc, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.reset, GPIO.OUT, initial=GPIO.HIGH)

        self.spi.open(bus, device)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed_hz
        self.spi.bits_per_word = 8

    def close(self) -> None:
        self.spi.close()
        GPIO.cleanup((self.dc, self.reset))

    def _write(self, dc: bool, payload: bytes) -> None:
        GPIO.output(self.dc, GPIO.HIGH if dc else GPIO.LOW)
        self.spi.writebytes2(payload)

    def command(self, command: int, data: bytes = b"") -> None:
        self._write(False, bytes((command,)))
        if data:
            self._write(True, data)

    def reset_panel(self) -> None:
        GPIO.output(self.reset, GPIO.HIGH)
        time.sleep(0.01)
        GPIO.output(self.reset, GPIO.LOW)
        time.sleep(0.12)
        GPIO.output(self.reset, GPIO.HIGH)
        time.sleep(0.20)

    def initialize(self) -> None:
        self.reset_panel()
        self.command(0x01)  # Software reset
        time.sleep(0.15)
        self.command(0x11)  # Sleep out
        time.sleep(0.12)

        # Manufacturer command-set unlock and panel timing values used by
        # common ST7796S SPI modules.
        sequence = (
            (0xF0, b"\xC3"),
            (0xF0, b"\x96"),
            (0x36, b"\x28"),  # Landscape, BGR, row/column exchange
            (0x3A, b"\x55"),  # RGB565 (16 bits per pixel)
            (0xB4, b"\x01"),
            (0xB7, b"\xC6"),
            (0xC0, b"\x80\x45"),
            (0xC1, b"\x13"),
            (0xC2, b"\xA7"),
            (0xC5, b"\x0A"),
            (0xE8, b"\x40\x8A\x00\x00\x29\x19\xA5\x33"),
            (0xE0, b"\xF0\x06\x0B\x07\x06\x05\x2E\x33\x47\x3A\x17\x16\x2E\x31"),
            (0xE1, b"\xF0\x09\x0D\x09\x08\x23\x2E\x33\x46\x38\x13\x13\x2C\x32"),
            (0xF0, b"\x3C"),
            (0xF0, b"\x69"),
            (0x20, b""),      # Display inversion off
            (0x13, b""),      # Normal display mode
        )
        for command, data in sequence:
            self.command(command, data)

        self.command(0x29)  # Display on
        time.sleep(0.10)

    def set_window(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.command(0x2A, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self.command(0x2B, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self.command(0x2C)

    def show(self, image: Image.Image) -> None:
        if image.size != (self.WIDTH, self.HEIGHT):
            raise ValueError(f"image must be {self.WIDTH}x{self.HEIGHT}")

        rgb = image.convert("RGB").tobytes()
        pixels = bytearray(self.WIDTH * self.HEIGHT * 2)
        out = 0
        for pos in range(0, len(rgb), 3):
            red, green, blue = rgb[pos], rgb[pos + 1], rgb[pos + 2]
            value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
            pixels[out] = value >> 8
            pixels[out + 1] = value & 0xFF
            out += 2

        self.set_window(0, 0, self.WIDTH - 1, self.HEIGHT - 1)
        self._write(True, pixels)


def hello_image() -> Image.Image:
    image = Image.new("RGB", (ST7796.WIDTH, ST7796.HEIGHT), "#101820")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 96
        )
    except OSError:
        font = ImageFont.load_default()

    text = "hello"
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = (ST7796.WIDTH - width) // 2
    y = (ST7796.HEIGHT - height) // 2 - box[1]
    draw.text((x, y), text, font=font, fill="#FEE715")
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed", type=int, default=20_000_000,
                        help="SPI clock in Hz (default: 20000000)")
    args = parser.parse_args()

    display = ST7796(speed_hz=args.speed)
    try:
        display.initialize()
        display.show(hello_image())
        print("Displayed 'hello' on the ST7796.")
    finally:
        display.close()


if __name__ == "__main__":
    main()
