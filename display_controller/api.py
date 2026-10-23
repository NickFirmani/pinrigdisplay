"""Standard-library HTTP API for the display controller."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from typing import Any, Callable
from urllib.parse import urlsplit

from .controller import DisplayController
from .display.st7796 import DisplayError
from .models import DisplayRequest, RequestValidationError


LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8_192


def _response_body(controller: DisplayController) -> dict[str, Any]:
    status = controller.status()
    return {
        **status.request.to_dict(),
        "healthy": status.healthy,
    }


def make_handler(controller: DisplayController) -> type[BaseHTTPRequestHandler]:
    class DisplayRequestHandler(BaseHTTPRequestHandler):
        server_version = "DisplayController/0.1"

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                status = controller.status()
                code = HTTPStatus.OK if status.healthy else HTTPStatus.SERVICE_UNAVAILABLE
                self._json(code, {
                    "status": "ok" if status.healthy else "unhealthy",
                    "page": status.request.page,
                })
                return
            if path == "/api/display":
                self._json(HTTPStatus.OK, _response_body(controller))
                return
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")

        def do_PUT(self) -> None:
            if urlsplit(self.path).path != "/api/display":
                self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
                return
            media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if media_type != "application/json":
                self._error(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "unsupported_media_type",
                    "Content-Type must be application/json",
                )
                return

            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._error(HTTPStatus.LENGTH_REQUIRED, "length_required",
                            "Content-Length is required")
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large",
                            f"request body cannot exceed {MAX_REQUEST_BYTES} bytes")
                return

            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._error(HTTPStatus.BAD_REQUEST, "invalid_json",
                            "request body is not valid JSON")
                return

            try:
                request = DisplayRequest.from_mapping(body)
                status = controller.set_page(request)
            except RequestValidationError as error:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_request", str(error))
                return
            except DisplayError as error:
                LOGGER.exception("Display update failed")
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "display_unavailable", str(error))
                return
            except OSError as error:
                LOGGER.exception("State persistence failed")
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "persistence_failed", str(error))
                return

            self._json(HTTPStatus.OK, {
                **status.request.to_dict(),
                "healthy": status.healthy,
            })

        def log_message(self, message: str, *args: object) -> None:
            LOGGER.info("%s - %s", self.address_string(), message % args)

        def _error(self, status: HTTPStatus, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    return DisplayRequestHandler


class DisplayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(host: str, port: int, controller: DisplayController) -> DisplayHTTPServer:
    return DisplayHTTPServer((host, port), make_handler(controller))
