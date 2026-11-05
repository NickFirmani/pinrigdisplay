"""Direct-SPI / Zero device runtime with optional HTTP and serial adapters."""
import argparse
import logging
from pathlib import Path
import signal
import threading
import time

from .api import create_server
from .config import load_config
from .controller import DisplayController
from .display.pages import PageRenderer
from .display.st7796 import ST7796
from .serial import SerialEndpoint
from .touch import TouchWorker, XPT2046
from pinrig_protocol.interactions import InteractionStore

LOGGER = logging.getLogger(__name__)


def build_controller(config, *, bus_lock=None):
    display = ST7796(bus_lock=bus_lock, **{name: getattr(config, field) for name, field in
        [('bus', 'spi_bus'), ('device', 'spi_device'), ('dc_pin', 'dc_pin'),
         ('reset_pin', 'reset_pin'), ('speed_hz', 'speed_hz'), ('madctl', 'madctl')]})
    try:
        store = InteractionStore(Path(config.interaction_path)) if config.touch_enabled else None
        return DisplayController(display=display, pages=PageRenderer(), interactions=store)
    except Exception:
        display.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.toml'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = load_config(args.config)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    bus_lock = threading.Lock()
    controller = build_controller(config, bus_lock=bus_lock)
    server = None
    worker = None
    touch = None
    serial = None
    reconnect_at = 0.
    backoff = 1.
    adapter = SerialEndpoint(controller)
    try:
        controller.start()
        if config.touch_enabled:
            try:
                touch = TouchWorker(XPT2046(bus_lock=bus_lock), controller)
                touch.start()
            except Exception as error:
                LOGGER.exception('Touch setup failed; display remains operational')
                controller.touch_failed(str(error))
        if config.http_enabled:
            server = create_server(config.host, config.port, controller)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
        while not stop.is_set():
            frame_started = time.monotonic()
            if config.serial_path and time.monotonic() >= reconnect_at:
                try:
                    if serial is None:
                        import serial as serial_module
                        serial = serial_module.Serial(config.serial_path, 115200, timeout=0, write_timeout=1)
                        adapter = SerialEndpoint(controller)
                        backoff = 1.
                    data = serial.read(8192)
                    if data:
                        reply = adapter.feed(data)
                        if reply and serial.write(reply) != len(reply):
                            raise OSError('short serial write')
                except OSError:
                    LOGGER.exception('Device serial connection unavailable')
                    reconnect_at = time.monotonic() + backoff
                    backoff = min(30., backoff * 2)
                    if serial is not None:
                        serial.close()
                        serial = None
                    # HTTP, lease expiry and rendering remain alive during reconnect.
            controller.tick()
            # Rendering time is part of the frame budget. Never add an entire
            # interval after a slow SPI write or try to catch up missed frames.
            interval = controller.frame_interval(config.animation_fps)
            stop.wait(max(0., interval - (time.monotonic() - frame_started)))
    finally:
        if touch:
            touch.close()
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join()
        if serial:
            serial.close()
        controller.close()


if __name__ == '__main__':
    main()
