from __future__ import annotations

import unittest

from PIL import Image

from display_controller.controller import DisplayController
from display_controller.display.st7796 import DisplayError
from display_controller.models import DisplayRequest


class FakeDisplay:
    def __init__(self) -> None:
        self.initialized = False
        self.closed = False
        self.writes: list[tuple[object, int, int]] = []
        self.fail_writes = False

    def initialize(self) -> None: self.initialized = True
    def write(self, frame: object, *, x: int = 0, y: int = 0) -> None:
        if self.fail_writes:
            raise DisplayError("test failure")
        self.writes.append((frame, x, y))
    def close(self) -> None: self.closed = True


class FakePages:
    def render(self, _request: DisplayRequest) -> Image.Image:
        return Image.new("RGB", (2, 2), "red")
    def on_air_frames(self, count: int) -> list[Image.Image]:
        return [Image.new("RGB", (1, 1), (index, 0, 0)) for index in range(count)]


class FakeState:
    def __init__(self, saved: DisplayRequest | None = None) -> None:
        self.saved = saved
        self.saves: list[DisplayRequest] = []
    def load(self) -> DisplayRequest | None: return self.saved
    def save(self, request: DisplayRequest) -> None: self.saves.append(request)


class FakeAnimator:
    def __init__(self) -> None:
        self.starts: list[tuple[list[object], float, object]] = []
        self.stop_count = 0
    def start(self, frames: list[object], *, interval: float, draw: object) -> None:
        self.starts.append((frames, interval, draw))
    def stop(self) -> None: self.stop_count += 1


class ControllerTests(unittest.TestCase):
    def make_controller(self, *, saved: DisplayRequest | None = None):
        display = FakeDisplay()
        state = FakeState(saved)
        animator = FakeAnimator()
        controller = DisplayController(
            display=display,
            pages=FakePages(),  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            animation_fps=8,
            pulse_seconds=1.0,
            animator=animator,  # type: ignore[arg-type]
        )
        return controller, display, state, animator

    def test_start_restores_saved_page_without_rewriting_state(self) -> None:
        saved = DisplayRequest(page="message", title="HELLO", body="World")
        controller, display, state, _animator = self.make_controller(saved=saved)

        controller.start()

        self.assertTrue(display.initialized)
        self.assertEqual(controller.status().request, saved)
        self.assertEqual(state.saves, [])

    def test_successful_update_is_displayed_then_saved(self) -> None:
        controller, display, state, _animator = self.make_controller()
        controller.start()
        request = DisplayRequest(page="message", title="PLAYER 2", body="Approach")

        status = controller.set_page(request)

        self.assertEqual(status.request, request)
        self.assertEqual(state.saves, [request])
        self.assertEqual(len(display.writes), 2)

    def test_failed_display_update_is_not_saved(self) -> None:
        controller, display, state, _animator = self.make_controller()
        controller.start()
        display.fail_writes = True

        with self.assertRaises(DisplayError):
            controller.set_page(DisplayRequest(page="on_air"))

        self.assertEqual(state.saves, [])
        self.assertFalse(controller.status().healthy)

    def test_on_air_starts_cached_partial_region_animation(self) -> None:
        controller, _display, _state, animator = self.make_controller()
        controller.start()

        controller.set_page(DisplayRequest(page="on_air"))
        controller.set_page(DisplayRequest(page="standby"))
        controller.set_page(DisplayRequest(page="on_air"))

        self.assertEqual(len(animator.starts), 2)
        self.assertIs(animator.starts[0][0], animator.starts[1][0])
        self.assertEqual(len(animator.starts[0][0]), 8)
        self.assertEqual(animator.starts[0][1], 0.125)

    def test_animation_failure_marks_controller_unhealthy(self) -> None:
        controller, display, _state, animator = self.make_controller()
        controller.start()
        controller.set_page(DisplayRequest(page="on_air"))
        display.fail_writes = True
        draw = animator.starts[0][2]

        with self.assertRaises(DisplayError):
            draw(animator.starts[0][0][0])  # type: ignore[operator]

        self.assertFalse(controller.status().healthy)

    def test_camera_pages_stop_live_animation_and_persist(self) -> None:
        for page in ("camera_active", "camera_inactive"):
            with self.subTest(page=page):
                controller, display, state, animator = self.make_controller()
                controller.start()
                controller.set_page(DisplayRequest(page="on_air"))
                stops_before = animator.stop_count
                request = DisplayRequest.from_mapping({"page": page})

                status = controller.set_page(request)

                self.assertTrue(status.healthy)
                self.assertEqual(status.request, request)
                self.assertEqual(state.saves[-1], request)
                self.assertEqual(animator.stop_count, stops_before + 1)
                self.assertEqual(len(animator.starts), 1)
                self.assertEqual(len(display.writes), 3)

                restored, _display, restored_state, restored_animator = self.make_controller(
                    saved=request,
                )
                restored.start()
                self.assertEqual(restored.status().request, request)
                self.assertEqual(restored_state.saves, [])
                self.assertEqual(restored_animator.starts, [])


if __name__ == "__main__":
    unittest.main()
