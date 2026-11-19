#!/usr/bin/env python3
"""Serve a small, interactive VideoNode-compatible API for rig diagnosis."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import select
import sys
import threading
import time
import termios
import tty

LOGGER = logging.getLogger("videonode-simulator")
DEFAULT_STREAMS = ["camera1", "camera2", "camera3", "combined"]


def parse_csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("provide at least one comma-separated value")
    return items


class VideoState:
    def __init__(self, stream_ids: list[str]):
        self.stream_ids = stream_ids
        self.counts = {stream_id: 0 for stream_id in stream_ids}
        self.lock = threading.Lock()

    def set_active(self, stream_id: str | None) -> None:
        with self.lock:
            self.counts = {item: int(item == stream_id) for item in self.stream_ids}

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return dict(self.counts)


def make_handler(state: VideoState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if self.path == "/api/streams":
                body = json.dumps({"streams": [{"stream_id": stream_id}
                                                for stream_id in state.stream_ids]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
                return

            if self.path != "/api/events":
                self.send_error(404, "route not found")
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    for stream_id, count in state.snapshot().items():
                        self._send_event("entity", {
                            "type": "stream.consumers",
                            "id": stream_id,
                            "payload": {"total": count},
                        })
                    self._send_event("heartbeat", {})
                    time.sleep(2)
            except (BrokenPipeError, ConnectionResetError, OSError):
                LOGGER.info("VideoNode event client disconnected")

        def _send_event(self, name: str, payload: dict) -> None:
            data = json.dumps(payload, separators=(",", ":"))
            self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode())
            self.wfile.flush()

        def log_message(self, format: str, *args) -> None:
            LOGGER.info("%s - %s", self.address_string(), format % args)

    return Handler


def show_menu(state: VideoState, mode: str) -> None:
    counts = state.snapshot()
    active = next((stream_id for stream_id, count in counts.items() if count), None)
    print(f"\nVideoNode simulator — {mode}; active stream: {active or 'none'}")
    print("  i  all streams inactive")
    for index, stream_id in enumerate(state.stream_ids, 1):
        print(f"  {index}  activate {stream_id}")
    print("  a  toggle auto mode")
    print("  m  manual mode")
    print("  q  quit")
    print("Key: ", end="", flush=True)


def run_console(state: VideoState, server: ThreadingHTTPServer, interval: float) -> None:
    if not sys.stdin.isatty():
        raise RuntimeError("interactive simulator needs a terminal")
    original = termios.tcgetattr(sys.stdin.fileno())
    mode, auto_index, next_auto = "manual", 0, time.monotonic() + interval
    try:
        tty.setcbreak(sys.stdin.fileno())
        show_menu(state, mode)
        while True:
            now = time.monotonic()
            if mode == "auto" and now >= next_auto:
                choices = [None, *state.stream_ids]
                state.set_active(choices[auto_index % len(choices)])
                auto_index += 1
                next_auto = now + interval
                show_menu(state, mode)
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue
            key = sys.stdin.read(1).lower()
            if key == "q":
                return
            if key == "a":
                mode = "manual" if mode == "auto" else "auto"
                next_auto = time.monotonic() + interval
            elif key == "m":
                mode = "manual"
            elif key == "i":
                mode = "manual"
                state.set_active(None)
            elif key.isdigit() and 1 <= int(key) <= len(state.stream_ids):
                mode = "manual"
                state.set_active(state.stream_ids[int(key) - 1])
            else:
                continue
            show_menu(state, mode)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost)")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--streams", type=parse_csv, default=DEFAULT_STREAMS,
                        help="comma-separated stream IDs (default: camera1,camera2,camera3,combined)")
    parser.add_argument("--interval", type=float, default=4.0,
                        help="seconds between automatic state changes (default: 4)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.interval <= 0:
        parser.error("interval must be greater than zero")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = VideoState(args.streams)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    LOGGER.info("Serving VideoNode simulator on http://%s:%d", args.host, args.port)
    try:
        run_console(state, server, args.interval)
    except KeyboardInterrupt:
        print("\nStopping VideoNode simulator")
        server.shutdown()
    except RuntimeError as error:
        parser.error(str(error))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
