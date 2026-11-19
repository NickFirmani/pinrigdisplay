"""Bounded UTF-8 JSON lines, recovering at the next newline after overflow."""
import json
from .commands import MAX_FRAME, error_response


def encode(value: dict) -> bytes:
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_FRAME:
        raise ValueError('frame too large')
    return data + b'\n'


class FrameError(dict):
    """Locally generated framing error, distinct from untrusted JSON objects."""


class Framer:
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, data: bytes) -> list[dict]:
        results = []
        for byte in data:
            if byte == 10:
                if self.discarding:
                    results.append(FrameError(error_response(None, 'invalid_frame', 'frame too large')))
                else:
                    try:
                        value = json.loads(self.buffer.decode('utf-8'))
                        if not isinstance(value, dict):
                            raise ValueError('expected JSON object')
                        results.append(value)
                    except (ValueError, UnicodeError, RecursionError):
                        results.append(FrameError(error_response(None, 'invalid_frame', 'invalid UTF-8 JSON object')))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_FRAME:
                    self.buffer.clear()
                    self.discarding = True
        return results
