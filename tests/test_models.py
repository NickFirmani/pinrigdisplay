from __future__ import annotations

import unittest

from display_controller.models import DisplayRequest, RequestValidationError


class DisplayRequestTests(unittest.TestCase):
    def test_accepts_each_page_shape(self) -> None:
        self.assertEqual(DisplayRequest.from_mapping({"page": "standby"}),
                         DisplayRequest(page="standby"))
        self.assertEqual(DisplayRequest.from_mapping({"page": " ON_AIR "}),
                         DisplayRequest(page="on_air"))
        self.assertEqual(
            DisplayRequest.from_mapping({
                "page": "message", "title": " PLAYER 2 ", "body": " Approach ",
            }),
            DisplayRequest(page="message", title="PLAYER 2", body="Approach"),
        )

    def test_message_requires_title_and_body(self) -> None:
        with self.assertRaisesRegex(RequestValidationError, "title is required"):
            DisplayRequest.from_mapping({"page": "message", "body": "Hello"})
        with self.assertRaisesRegex(RequestValidationError, "body is required"):
            DisplayRequest.from_mapping({"page": "message", "title": "Hello"})

    def test_rejects_unknown_pages_and_fields(self) -> None:
        with self.assertRaisesRegex(RequestValidationError, "page must be one of"):
            DisplayRequest.from_mapping({"page": "unknown"})
        with self.assertRaisesRegex(RequestValidationError, "unknown field"):
            DisplayRequest.from_mapping({"page": "standby", "extra": True})
        with self.assertRaisesRegex(RequestValidationError, "does not accept title"):
            DisplayRequest.from_mapping({"page": "on_air", "title": "no"})

    def test_rejects_oversized_message(self) -> None:
        with self.assertRaisesRegex(RequestValidationError, "at most 40"):
            DisplayRequest.from_mapping({
                "page": "message", "title": "x" * 41, "body": "valid",
            })


if __name__ == "__main__":
    unittest.main()
