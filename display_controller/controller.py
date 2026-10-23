"""Application service coordinating pages, persistence, and hardware."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Protocol

from .animation import FrameAnimator
from .display.pages import ON_AIR_REGION, PageRenderer
from .display.renderer import Frame, encode_rgb565
from .display.st7796 import DisplayError
from .models import DisplayRequest
from .state import StateStore


LOGGER = logging.getLogger(__name__)


class Display(Protocol):
    def initialize(self) -> None: ...
    def write(self, frame: Frame, *, x: int = 0, y: int = 0) -> None: ...
    def close(self) -> None: ...


class Animator(Protocol):
    def start(self, frames: list[Frame], *, interval: float,
              draw: object) -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True)
class ControllerStatus:
    healthy: bool
    request: DisplayRequest


class DisplayController:
    def __init__(self, *, display: Display, pages: PageRenderer,
                 state: StateStore, animation_fps: int,
                 pulse_seconds: float,
                 animator: FrameAnimator | None = None) -> None:
        self._display = display
        self._pages = pages
        self._state = state
        self._animation_fps = animation_fps
        self._pulse_seconds = pulse_seconds
        self._animator = animator or FrameAnimator()
        self._lock = threading.RLock()
        self._request = DisplayRequest(page="standby")
        self._healthy = False
        self._animation_frames: list[Frame] | None = None

    def start(self) -> None:
        """Initialize hardware and restore the last successful request."""
        with self._lock:
            try:
                self._display.initialize()
                self._healthy = True
                self._apply(self._state.load() or DisplayRequest(page="standby"),
                            persist=False)
            except Exception:
                self._healthy = False
                self._animator.stop()
                raise

    def set_page(self, request: DisplayRequest) -> ControllerStatus:
        with self._lock:
            self._apply(request, persist=True)
            return self.status()

    def status(self) -> ControllerStatus:
        with self._lock:
            return ControllerStatus(self._healthy, self._request)

    def close(self) -> None:
        with self._lock:
            self._animator.stop()
            self._display.close()
            self._healthy = False

    def _apply(self, request: DisplayRequest, *, persist: bool) -> None:
        self._animator.stop()
        try:
            image = self._pages.render(request)
            self._display.write(encode_rgb565(image))
            if request.page == "on_air":
                self._start_on_air_animation()
        except Exception as error:
            self._healthy = False
            if isinstance(error, DisplayError):
                raise
            raise DisplayError(f"could not display {request.page}: {error}") from error

        self._request = request
        self._healthy = True
        if persist:
            self._state.save(request)
        LOGGER.info("Displayed page %s", request.page)

    def _start_on_air_animation(self) -> None:
        if self._animation_frames is None:
            count = max(2, round(self._animation_fps * self._pulse_seconds))
            self._animation_frames = [
                encode_rgb565(image) for image in self._pages.on_air_frames(count)
            ]
        x, y = ON_AIR_REGION[:2]

        def draw(frame: Frame) -> None:
            try:
                self._display.write(frame, x=x, y=y)
            except Exception:
                self._healthy = False
                raise

        self._animator.start(
            self._animation_frames,
            interval=1.0 / self._animation_fps,
            draw=draw,
        )
