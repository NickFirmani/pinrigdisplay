from __future__ import annotations

import unittest

from display_controller.display.renderer import Frame
from display_controller.display.st7796 import ST7796


class FakeGPIO:
    BCM = "BCM"
    OUT = "OUT"
    LOW = 0
    HIGH = 1

    def __init__(self) -> None:
        self.outputs: list[tuple[int, int]] = []
        self.cleaned: list[tuple[int, int]] = []

    def setwarnings(self, _enabled: bool) -> None: pass
    def setmode(self, _mode: str) -> None: pass
    def setup(self, _pin: int, _mode: str, *, initial: int) -> None: pass
    def output(self, pin: int, value: int) -> None: self.outputs.append((pin, value))
    def cleanup(self, pins: tuple[int, int]) -> None: self.cleaned.append(pins)


class FakeSPI:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.opened: tuple[int, int] | None = None
        self.closed = 0

    def open(self, bus: int, device: int) -> None: self.opened = (bus, device)
    def writebytes2(self, payload: bytes) -> None: self.writes.append(bytes(payload))
    def close(self) -> None: self.closed += 1


class ST7796Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.gpio = FakeGPIO()
        self.spi = FakeSPI()
        self.sleeps: list[float] = []
        self.display = ST7796(
            gpio=self.gpio, spi=self.spi, sleep=self.sleeps.append,
            speed_hz=12_000_000,
        )

    def test_initialization_uses_expected_reset_delays_and_commands(self) -> None:
        self.display.initialize()

        self.assertEqual(self.spi.opened, (0, 0))
        self.assertEqual(self.spi.max_speed_hz, 12_000_000)
        self.assertEqual(self.sleeps, [0.01, 0.12, 0.20, 0.15, 0.12, 0.10])
        self.assertIn(b"\x11", self.spi.writes)
        self.assertIn(b"\x29", self.spi.writes)

    def test_writes_exact_region_window_and_pixels(self) -> None:
        pixels = bytes.fromhex("f80007e0")
        self.display.write(Frame(2, 1, pixels), x=10, y=20)

        self.assertEqual(self.spi.writes, [
            b"\x2a", b"\x00\x0a\x00\x0b",
            b"\x2b", b"\x00\x14\x00\x14",
            b"\x2c", pixels,
        ])

    def test_rejects_region_outside_display(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            self.display.write(Frame(2, 1, b"\x00" * 4), x=479, y=0)

    def test_close_is_idempotent(self) -> None:
        self.display.close()
        self.display.close()
        self.assertEqual(self.spi.closed, 1)
        self.assertEqual(self.gpio.cleaned, [(24, 25)])


if __name__ == "__main__":
    unittest.main()
