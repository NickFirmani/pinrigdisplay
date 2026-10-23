from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from display_controller.models import DisplayRequest
from display_controller.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_round_trips_state_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            store = StateStore(path)
            request = DisplayRequest(page="message", title="PLAYER 2", body="Approach")

            store.save(request)

            self.assertEqual(store.load(), request)
            self.assertEqual(json.loads(path.read_text()), request.to_dict())
            self.assertEqual(list(path.parent.glob(".state.json.*")), [])

    def test_missing_or_invalid_state_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            self.assertIsNone(store.load())
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(store.load())
            path.write_text('{"page":"unknown"}', encoding="utf-8")
            self.assertIsNone(store.load())


if __name__ == "__main__":
    unittest.main()
