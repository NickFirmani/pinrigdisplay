"""Minimal ST7796 SPI display adapter for Raspberry Pi."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .renderer import Frame


class DisplayError(RuntimeError):
    """The display could not be initialized or updated."""


class ST7796:
    WIDTH = 480
    HEIGHT = 320

    def __init__(
        self,
        *,
        bus: int = 0,
        device: int = 0,
        dc_pin: int = 24,
        reset_pin: int = 25,
        speed_hz: int = 20_000_000,
        madctl: int = 0x28,
        gpio: Any | None = None,
        spi: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if gpio is None:
            import RPi.GPIO as gpio_module
            gpio = gpio_module
        if spi is None:
            import spidev
            spi = spidev.SpiDev()

        self._gpio = gpio
        self._spi = spi
        self._dc_pin = dc_pin
        self._reset_pin = reset_pin
        self._madctl = madctl
        self._sleep = sleep
        self._lock = threading.Lock()
        self._closed = False

        try:
            gpio.setwarnings(False)
            gpio.setmode(gpio.BCM)
            gpio.setup(dc_pin, gpio.OUT, initial=gpio.LOW)
            gpio.setup(reset_pin, gpio.OUT, initial=gpio.HIGH)
            spi.open(bus, device)
            spi.mode = 0
            spi.max_speed_hz = speed_hz
            spi.bits_per_word = 8
        except Exception as error:
            raise DisplayError(f"failed to open SPI/GPIO: {error}") from error

    def initialize(self) -> None:
        """Reset and configure the controller for 480x320 RGB565 output."""
        try:
            with self._lock:
                self._gpio.output(self._reset_pin, self._gpio.HIGH)
                self._sleep(0.01)
                self._gpio.output(self._reset_pin, self._gpio.LOW)
                self._sleep(0.12)
                self._gpio.output(self._reset_pin, self._gpio.HIGH)
                self._sleep(0.20)

                self._command(0x01)
                self._sleep(0.15)
                self._command(0x11)
                self._sleep(0.12)

                for command, data in (
                    (0xF0, b"\xC3"),
                    (0xF0, b"\x96"),
                    (0x36, bytes((self._madctl,))),
                    (0x3A, b"\x55"),
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
                    (0x20, b""),
                    (0x13, b""),
                ):
                    self._command(command, data)

                self._command(0x29)
                self._sleep(0.10)
        except Exception as error:
            if isinstance(error, DisplayError):
                raise
            raise DisplayError(f"failed to initialize display: {error}") from error

    def write(self, frame: Frame, *, x: int = 0, y: int = 0) -> None:
        """Write a full frame or rectangular region to display memory."""
        if x < 0 or y < 0:
            raise ValueError("frame coordinates cannot be negative")
        if x + frame.width > self.WIDTH or y + frame.height > self.HEIGHT:
            raise ValueError("frame falls outside the display")

        try:
            with self._lock:
                self._set_window(x, y, x + frame.width - 1, y + frame.height - 1)
                self._write(True, frame.pixels)
        except Exception as error:
            raise DisplayError(f"failed to write display frame: {error}") from error

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._spi.close()
        finally:
            self._gpio.cleanup((self._dc_pin, self._reset_pin))

    def _write(self, is_data: bool, payload: bytes) -> None:
        self._gpio.output(
            self._dc_pin, self._gpio.HIGH if is_data else self._gpio.LOW
        )
        self._spi.writebytes2(payload)

    def _command(self, command: int, data: bytes = b"") -> None:
        self._write(False, bytes((command,)))
        if data:
            self._write(True, data)

    def _set_window(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self._command(0x2A, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._command(0x2B, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self._command(0x2C)
