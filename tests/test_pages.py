from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image, ImageDraw, ImageFont

from display_controller.display.pages import (
    HEIGHT, ON_AIR_REGION, WIDTH, PageRenderer, _wrap,
)
from display_controller.models import DisplayRequest


ROOT = Path(__file__).resolve().parents[1]


class PageRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = PageRenderer(ROOT / "assets" / "logo.png")

    def test_every_page_has_display_dimensions(self) -> None:
        requests = [
            DisplayRequest(page="standby"),
            DisplayRequest(page="on_air"),
            DisplayRequest(page="message", title="PLAYER 2",
                           body="Please approach the machine"),
        ]
        for request in requests:
            with self.subTest(page=request.page):
                self.assertEqual(self.pages.render(request).size, (WIDTH, HEIGHT))

    def test_on_air_animation_is_deterministic_and_changes_brightness(self) -> None:
        first = self.pages.on_air_frames(8)
        second = self.pages.on_air_frames(8)
        region_size = (ON_AIR_REGION[2] - ON_AIR_REGION[0],
                       ON_AIR_REGION[3] - ON_AIR_REGION[1])

        self.assertEqual([frame.size for frame in first], [region_size] * 8)
        self.assertEqual(first[0].tobytes(), second[0].tobytes())
        self.assertNotEqual(first[0].tobytes(), first[4].tobytes())

    def test_long_message_renders_without_exceeding_canvas(self) -> None:
        image = self.pages.message(
            "A LONG PLAYER TITLE",
            "This intentionally long message verifies deterministic wrapping "
            "and truncation within the available message panel area.",
        )
        self.assertEqual(image.getbbox(), (0, 0, WIDTH, HEIGHT))

    def test_wrap_splits_unbroken_text_and_marks_truncation(self) -> None:
        image = Image.new("RGB", (200, 100))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20
        )

        lines = _wrap(draw, "X" * 100, font, width=80, maximum_lines=3)

        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(draw.textlength(line, font=font) <= 80 for line in lines))


if __name__ == "__main__":
    unittest.main()
