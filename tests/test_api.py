from __future__ import annotations

from http.client import HTTPConnection
import json
import threading
import unittest

from display_controller.api import create_server
from display_controller.controller import ControllerStatus
from display_controller.models import DisplayRequest


class FakeController:
    def __init__(self) -> None:
        self.request = DisplayRequest(page="standby")
    def status(self) -> ControllerStatus:
        return ControllerStatus(True, self.request)
    def set_page(self, request: DisplayRequest) -> ControllerStatus:
        self.request = request
        return self.status()


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = FakeController()
        self.server = create_server("127.0.0.1", 0, self.controller)  # type: ignore[arg-type]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)

    def tearDown(self) -> None:
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method: str, path: str, body: object | None = None,
                content_type: str = "application/json") -> tuple[int, dict]:
        encoded = None if body is None else json.dumps(body)
        headers = {} if body is None else {"Content-Type": content_type}
        self.connection.request(method, path, body=encoded, headers=headers)
        response = self.connection.getresponse()
        return response.status, json.loads(response.read())

    def test_put_and_get_display(self) -> None:
        status, body = self.request("PUT", "/api/display", {
            "page": "message", "title": "PLAYER 2", "body": "Please approach",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["page"], "message")

        status, body = self.request("GET", "/api/display")
        self.assertEqual(status, 200)
        self.assertEqual(body, {
            "page": "message", "title": "PLAYER 2",
            "body": "Please approach", "healthy": True,
        })

    def test_health_endpoint(self) -> None:
        status, body = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok", "page": "standby"})

    def test_camera_pages_can_be_selected_and_read_back(self) -> None:
        for page in ("camera_active", "camera_inactive"):
            with self.subTest(page=page):
                status, body = self.request("PUT", "/api/display", {"page": page})
                self.assertEqual(status, 200)
                self.assertEqual(body["page"], page)
                status, body = self.request("GET", "/api/display")
                self.assertEqual(status, 200)
                self.assertEqual(body, {"page": page, "healthy": True})

    def test_invalid_requests_have_structured_errors(self) -> None:
        status, body = self.request("PUT", "/api/display", {"page": "missing"})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "invalid_request")

        status, body = self.request("PUT", "/api/display", {"page": "standby"},
                                    content_type="text/plain")
        self.assertEqual(status, 415)
        self.assertEqual(body["error"]["code"], "unsupported_media_type")

    def test_unknown_route_returns_404(self) -> None:
        status, body = self.request("GET", "/missing")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
