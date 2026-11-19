#!/usr/bin/env python3
"""Serve an interactive OBS WebSocket v5 simulator for pinrig-stream."""

import argparse
import base64
import hashlib
import json
import logging
import select
import socketserver
import struct
import sys
import threading
import time
import termios
import tty

LOGGER = logging.getLogger("obs-simulator")
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 65536
DEFAULT_SCENES = ["Rig 1", "Rig 2", "MEGA PINBALL", "Intermission"]


def parse_csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("provide at least one comma-separated value")
    return items


class OBSState:
    def __init__(self, scenes: list[str]):
        self.scenes = scenes
        self.scene = scenes[0]
        self.streaming = True
        self.lock = threading.Lock()

    def set_scene(self, scene: str) -> None:
        with self.lock:
            self.scene = scene

    def toggle_streaming(self) -> None:
        with self.lock:
            self.streaming = not self.streaming

    def set_auto(self, index: int) -> None:
        with self.lock:
            self.scene = self.scenes[index % len(self.scenes)]
            self.streaming = (index // len(self.scenes)) % 2 == 0

    def snapshot(self) -> tuple[str, bool]:
        with self.lock:
            return self.scene, self.streaming


def read_exact(stream, length: int) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise ConnectionError("incomplete WebSocket frame")
    return data


def send_frame(stream, opcode: int, payload: bytes) -> None:
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, length))
    elif length <= 0xFFFF:
        header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
    stream.write(header + payload)
    stream.flush()


def receive_frame(stream) -> tuple[int, bytes]:
    first, second = read_exact(stream, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(stream, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(stream, 8))[0]
    if length > MAX_MESSAGE:
        raise ValueError("OBS WebSocket message too large")
    mask = read_exact(stream, 4) if masked else b""
    payload = read_exact(stream, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


class SimulatorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            self._upgrade()
            self._send_json({"op": 0, "d": {"obsWebSocketVersion": "5.0.0",
                                               "rpcVersion": 1}})
            while True:
                opcode, payload = receive_frame(self.rfile)
                if opcode == 8:
                    send_frame(self.wfile, 8, payload)
                    return
                if opcode == 9:
                    send_frame(self.wfile, 10, payload)
                    continue
                if opcode != 1:
                    continue
                message = json.loads(payload)
                if not isinstance(message, dict):
                    raise ValueError("expected a JSON object")
                if message.get("op") == 1:
                    self._send_json({"op": 2, "d": {"negotiatedRpcVersion": 1}})
                elif message.get("op") == 6:
                    self._respond(message.get("d"))
        except (BrokenPipeError, ConnectionError, ConnectionResetError, OSError,
                ValueError, json.JSONDecodeError) as error:
            LOGGER.info("OBS WebSocket client disconnected: %s", error)

    def _upgrade(self) -> None:
        headers = {}
        total = len(self.rfile.readline(4097))
        while True:
            line = self.rfile.readline(4097)
            total += len(line)
            if total > 16384 or not line:
                raise ValueError("invalid WebSocket upgrade request")
            if line in (b"\r\n", b"\n"):
                break
            name, separator, value = line.decode("latin-1").partition(":")
            if separator:
                headers[name.strip().lower()] = value.strip()
        key = headers.get("sec-websocket-key")
        if not key or headers.get("upgrade", "").lower() != "websocket":
            raise ValueError("expected a WebSocket upgrade")
        accept = base64.b64encode(hashlib.sha1((key + WEBSOCKET_GUID).encode()).digest()).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
        )
        self.wfile.write(response.encode("ascii"))
        self.wfile.flush()

    def _respond(self, request: object) -> None:
        if not isinstance(request, dict):
            raise ValueError("invalid OBS request")
        request_type = request.get("requestType")
        request_id = request.get("requestId")
        if not isinstance(request_type, str) or not isinstance(request_id, str):
            raise ValueError("OBS request needs requestType and requestId")
        scene, streaming = self.server.state.snapshot()
        if request_type == "GetStreamStatus":
            data = {"outputActive": streaming}
        elif request_type == "GetCurrentProgramScene":
            data = {"currentProgramSceneName": scene}
        else:
            data = {}
        self._send_json({"op": 7, "d": {
            "requestType": request_type,
            "requestId": request_id,
            "requestStatus": {"result": True, "code": 100},
            "responseData": data,
        }})

    def _send_json(self, value: dict) -> None:
        send_frame(self.wfile, 1, json.dumps(value, separators=(",", ":")).encode())


class SimulatorServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def show_menu(state: OBSState, mode: str) -> None:
    scene, streaming = state.snapshot()
    print(f"\nOBS simulator — {mode}; streaming: {'yes' if streaming else 'no'}; scene: {scene}")
    for index, name in enumerate(state.scenes, 1):
        print(f"  {index}  set program scene to {name}")
    print("  s  toggle streaming")
    print("  a  toggle auto mode")
    print("  m  manual mode")
    print("  q  quit")
    print("Key: ", end="", flush=True)


def run_console(state: OBSState, server: SimulatorServer, interval: float) -> None:
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
                state.set_auto(auto_index)
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
            elif key == "s":
                mode = "manual"
                state.toggle_streaming()
            elif key.isdigit() and 1 <= int(key) <= len(state.scenes):
                mode = "manual"
                state.set_scene(state.scenes[int(key) - 1])
            else:
                continue
            show_menu(state, mode)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost)")
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--scenes", type=parse_csv, default=DEFAULT_SCENES,
                        help="scene names (default: Rig 1,Rig 2,MEGA PINBALL,Intermission)")
    parser.add_argument("--interval", type=float, default=4.0,
                        help="seconds between automatic state changes (default: 4)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.interval <= 0:
        parser.error("interval must be greater than zero")
    if len(args.scenes) > 9:
        parser.error("interactive scene selection supports at most 9 scenes")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = OBSState(args.scenes)
    server = SimulatorServer((args.host, args.port), SimulatorHandler)
    server.state = state
    threading.Thread(target=server.serve_forever, daemon=True).start()
    LOGGER.info("Serving OBS WebSocket simulator on ws://%s:%d", args.host, args.port)
    try:
        run_console(state, server, args.interval)
    except KeyboardInterrupt:
        print("\nStopping OBS WebSocket simulator")
    except RuntimeError as error:
        parser.error(str(error))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
