"""A stoppable background loop for cycling pre-rendered frames."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Sequence

from .display.renderer import Frame


LOGGER = logging.getLogger(__name__)


class FrameAnimator:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, frames: Sequence[Frame], *, interval: float,
              draw: Callable[[Frame], None]) -> None:
        if not frames:
            raise ValueError("animation must contain at least one frame")
        if interval <= 0:
            raise ValueError("animation interval must be positive")
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(tuple(frames), interval, draw),
            name="display-animation",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        if thread is not threading.current_thread():
            thread.join()
        self._thread = None

    def _run(self, frames: Sequence[Frame], interval: float,
             draw: Callable[[Frame], None]) -> None:
        index = 0
        deadline = time.monotonic()
        while True:
            deadline += interval
            if self._stop.wait(max(0.0, deadline - time.monotonic())):
                return
            try:
                draw(frames[index])
            except Exception:
                LOGGER.exception("Animation frame failed; stopping animation")
                return
            index = (index + 1) % len(frames)
