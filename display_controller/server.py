"""Application entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import threading

from .api import create_server
from .config import AppConfig, load_config
from .controller import DisplayController
from .display.pages import PageRenderer
from .display.st7796 import ST7796
from .state import StateStore


LOGGER = logging.getLogger(__name__)


def build_controller(config: AppConfig) -> DisplayController:
    display = ST7796(
        bus=config.display.spi_bus,
        device=config.display.spi_device,
        dc_pin=config.display.dc_pin,
        reset_pin=config.display.reset_pin,
        speed_hz=config.display.speed_hz,
        madctl=config.display.madctl,
    )
    return DisplayController(
        display=display,
        pages=PageRenderer(config.pages.logo_path),
        state=StateStore(config.state_path),
        animation_fps=config.pages.animation_fps,
        pulse_seconds=config.pages.pulse_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ST7796 display API")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--log-level", default="INFO")
    arguments = parser.parse_args()

    logging.basicConfig(
        level=arguments.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(arguments.config)
    controller = build_controller(config)
    server = create_server(config.server.host, config.server.port, controller)

    def stop_server(_signum: int, _frame: object) -> None:
        LOGGER.info("Shutdown requested")
        # BaseServer.shutdown() must run outside the serve_forever thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)

    try:
        controller.start()
        LOGGER.info("Listening on http://%s:%d", config.server.host, config.server.port)
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        controller.close()


if __name__ == "__main__":
    main()
