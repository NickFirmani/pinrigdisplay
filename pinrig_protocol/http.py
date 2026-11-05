"""One bounded HTTP transport for local device and remote host command handlers."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from .commands import MAX_FRAME, error_response

CODES = {'invalid_request': 422, 'unsupported_version': 422, 'invalid_frame': 400,
         'request_conflict': 409, 'session_changed': 409, 'queue_full': 429,
         'retry_capacity': 429, 'not_found': 404, 'ack_unavailable': 422}


def make_handler(endpoint):
    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def setup(self):
            super().setup()
            self.connection.settimeout(self.timeout)

        def do_GET(self):
            if self.path != '/healthz':
                self.send_json(404, error_response(None, 'not_found', 'use POST /api/commands'))
                return
            self.send_json(200, {'process': 'running'})

        def do_POST(self):
            if self.path != '/api/commands':
                self.send_json(404, error_response(None, 'not_found', 'route not found'))
                return
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                self.send_json(415, error_response(None, 'invalid_request', 'use application/json and Content-Length'))
                return
            try:
                length = int(self.headers.get('Content-Length', ''))
                if not 0 < length <= MAX_FRAME:
                    raise ValueError()
            except ValueError:
                self.send_json(413, error_response(None, 'invalid_frame', 'invalid or excessive Content-Length'))
                return
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError()
                value = json.loads(raw)
            except (ValueError, UnicodeError, OSError, RecursionError):
                self.send_json(400, error_response(None, 'invalid_frame', 'invalid JSON body'))
                return
            reply = endpoint.handle(value)
            code = 200 if reply['ok'] else CODES.get(reply['error']['code'], 503)
            self.send_json(code, reply)

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
    return Handler


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


def create_server(host, port, endpoint):
    return HTTPServer((host, port), make_handler(endpoint))
