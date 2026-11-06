import importlib.util
import sys
from pathlib import Path
from pinrig_protocol import commands
from pinrig_protocol.framing import FrameError, Framer, encode
spec = importlib.util.spec_from_file_location('test_pico_device', Path(__file__).resolve().parents[1] / 'firmware/pico/core.py')
core = importlib.util.module_from_spec(spec)
sys.modules['commands'] = commands
spec.loader.exec_module(core)
sys.modules.pop('commands')

class Store:
    def __init__(self): self.items = []
    def pending(self): return list(self.items)
    def append(self, item): self.items.append(item)
    def confirm(self, mid): self.items = [x for x in self.items if x['interaction_id'] != mid]

class SerialEndpoint:
    def __init__(self, controller): self.controller = controller; self.framer = Framer()
    def feed(self, data):
        return b''.join(encode(v if isinstance(v, FrameError) else self.controller.handle(v)) for v in self.framer.feed(data))



class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class Display:
    def __init__(self): self.frames = []; self.closed = 0; self.fail = False
    def render(self, *args):
        if self.fail: raise OSError("display failed")
        self.frames.append(args)
    def initialize(self): pass
    def close(self): self.closed += 1
    def write(self, frame, **coords):
        if self.fail: raise OSError('display failed')
        self.frames.append((frame, coords))


def device():
    clock = Clock()
    display = Display()
    controller = core.Device(display, Store(), clock, 'boot', lambda: 'interaction-1')
    controller.tick()
    return controller, clock, display


def command(op, rid='r1', **params):
    return {'version': 1, 'request_id': rid, 'session': 'boot', 'operation': op, 'params': params}
