"""Bounded HTTP server and JSON response helpers for Linux services."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging


class JSONHandler(BaseHTTPRequestHandler):
    timeout = 5

    def setup(self):
        super().setup()
        self.connection.settimeout(self.timeout)

    def send_json(self, code, value):
        body = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, message, *args):
        logging.getLogger(__name__).info(message, *args)


class HTTPServer(ThreadingHTTPServer):
    """Bound active connections as well as the listening backlog."""
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, handler):
        import threading
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
