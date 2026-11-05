"""Ordered local and serial delivery with bounded request/response exchange."""
import time
from pinrig_protocol.framing import Framer, encode


class LocalDelivery:
    def __init__(self, controller):
        self.controller = controller

    def exchange(self, command: dict) -> dict:
        return self.controller.handle(command)

    def close(self) -> None:
        pass


class SerialDelivery:
    """Caller serializes exchanges. A timeout leaves delivery uncertain."""
    def __init__(self, opener, *, clock=time.monotonic, timeout=2.):
        self.opener = opener
        self.clock = clock
        self.timeout = timeout
        self.stream = None
        self.framer = Framer()

    def exchange(self, command: dict) -> dict:
        try:
            if self.stream is None:
                self.stream = self.opener()
                self.framer = Framer()
            frame = encode(command)
            if self.stream.write(frame) != len(frame):
                raise OSError('short serial write; delivery uncertain')
            deadline = self.clock() + self.timeout
            while self.clock() < deadline:
                for reply in self.framer.feed(self.stream.read(8192)):
                    if reply.get('request_id') == command['request_id']:
                        if reply.get('version') != 1 or type(reply.get('ok')) is not bool:
                            raise OSError('invalid device response')
                        if reply['ok'] and not isinstance(reply.get('result'), dict):
                            raise OSError('invalid device result')
                        if not reply['ok'] and not isinstance(reply.get('error'), dict):
                            raise OSError('invalid device error')
                        return reply
            raise TimeoutError('device response timeout; delivery uncertain')
        except (OSError, ValueError):
            self.close()
            raise

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.close()
            finally:
                self.stream = None
