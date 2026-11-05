"""Small validated device configuration; no restored display state."""
from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class AppConfig:
    touch_enabled: bool = False
    interaction_path: str = '/var/lib/display-controller/interactions.sqlite3'
    host: str = '127.0.0.1'
    port: int = 48193
    http_enabled: bool = True
    serial_path: str | None = None
    animation_fps: int = 8
    spi_bus: int = 0
    spi_device: int = 0
    dc_pin: int = 24
    reset_pin: int = 25
    speed_hz: int = 20_000_000
    madctl: int = 0x28


def load_config(path: Path) -> AppConfig:
    with path.open('rb') as stream:
        data = tomllib.load(stream)
    if set(data) - set(AppConfig.__dataclass_fields__):
        raise ValueError('unknown configuration field')
    c = AppConfig(**data)
    for name, low, high in [('port', 1024, 65535), ('animation_fps', 1, 30),
                          ('spi_bus', 0, 9), ('spi_device', 0, 9), ('dc_pin', 0, 53),
                          ('reset_pin', 0, 53), ('speed_hz', 100_000, 80_000_000), ('madctl', 0, 255)]:
        v = getattr(c, name)
        if type(v) is not int or not low <= v <= high:
            raise ValueError(f'{name} must be between {low} and {high}')
    if type(c.http_enabled) is not bool or not isinstance(c.host, str) or not c.host.strip():
        raise ValueError('invalid HTTP configuration')
    if c.serial_path is not None and (not isinstance(c.serial_path, str) or not c.serial_path.startswith('/')):
        raise ValueError('serial_path must be absolute')
    if not c.http_enabled and not c.serial_path:
        raise ValueError('enable at least one command transport')
    if type(c.touch_enabled) is not bool or not isinstance(c.interaction_path, str) or not c.interaction_path.startswith('/'):
        raise ValueError('touch_enabled must be boolean and interaction_path absolute')
    if c.touch_enabled and (c.spi_bus != 0 or c.spi_device != 0):
        raise ValueError('touch requires the display on SPI0 CE0 and touch on CE1')
    if c.dc_pin == c.reset_pin:
        raise ValueError('DC and RESET must use different GPIO pins')
    return c
