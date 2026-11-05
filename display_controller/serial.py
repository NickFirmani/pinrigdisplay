"""Device-side JSON-lines adapter; serial handles are owned by the runtime."""
from pinrig_protocol.framing import FrameError, Framer, encode


class SerialEndpoint:
    def __init__(self, controller):
        self.controller = controller
        self.framer = Framer()

    def feed(self, data: bytes) -> bytes:
        return b''.join(encode(value if isinstance(value, FrameError)
                               else self.controller.handle(value))
                        for value in self.framer.feed(data))
