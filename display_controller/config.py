"""Typed application configuration loaded from TOML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 48193


@dataclass(frozen=True)
class DisplayConfig:
    spi_bus: int = 0
    spi_device: int = 0
    dc_pin: int = 24
    reset_pin: int = 25
    speed_hz: int = 20_000_000
    madctl: int = 0x28


@dataclass(frozen=True)
class PageConfig:
    logo_path: Path
    animation_fps: int = 8
    pulse_seconds: float = 4.0


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    display: DisplayConfig
    pages: PageConfig
    state_path: Path


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a TOML table")
    return value


def _integer(section: dict[str, Any], key: str, default: int,
             *, minimum: int, maximum: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _number(section: dict[str, Any], key: str, default: float,
            *, minimum: float, maximum: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return result


def _path(value: object, *, base: Path, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def load_config(path: Path) -> AppConfig:
    """Load and validate application configuration from *path*."""
    with path.open("rb") as config_file:
        data = tomllib.load(config_file)

    server = _section(data, "server")
    display = _section(data, "display")
    pages = _section(data, "pages")
    state = _section(data, "state")

    host = server.get("host", "0.0.0.0")
    if not isinstance(host, str) or not host:
        raise ValueError("host must be a non-empty string")

    logo_path = _path(
        pages.get("logo_path", "assets/logo.png"),
        base=path.parent,
        name="logo_path",
    )
    state_path = _path(
        state.get("path", "/var/lib/display-controller/state.json"),
        base=path.parent,
        name="state path",
    )

    return AppConfig(
        server=ServerConfig(
            host=host,
            port=_integer(server, "port", 48193, minimum=1024, maximum=65535),
        ),
        display=DisplayConfig(
            spi_bus=_integer(display, "spi_bus", 0, minimum=0, maximum=9),
            spi_device=_integer(display, "spi_device", 0, minimum=0, maximum=9),
            dc_pin=_integer(display, "dc_pin", 24, minimum=0, maximum=53),
            reset_pin=_integer(display, "reset_pin", 25, minimum=0, maximum=53),
            speed_hz=_integer(
                display, "speed_hz", 20_000_000,
                minimum=100_000, maximum=80_000_000,
            ),
            madctl=_integer(display, "madctl", 0x28, minimum=0, maximum=255),
        ),
        pages=PageConfig(
            logo_path=logo_path,
            animation_fps=_integer(
                pages, "animation_fps", 8, minimum=1, maximum=30,
            ),
            pulse_seconds=_number(
                pages, "pulse_seconds", 4.0, minimum=0.5, maximum=20.0,
            ),
        ),
        state_path=state_path,
    )
