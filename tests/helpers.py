from PIL import Image
from display_controller.controller import DisplayController


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class Display:
    def __init__(self): self.frames = []; self.closed = 0; self.fail = False
    def initialize(self): pass
    def close(self): self.closed += 1
    def write(self, frame, **coords):
        if self.fail: raise OSError('display failed')
        self.frames.append((frame, coords))


class Pages:
    def compose(self, state, message, diagnostic, height, seconds):
        return Image.new('RGB', (8, 8), {'unknown': 'gray', 'on_air': 'red',
                         'camera_active': 'yellow', 'camera_inactive': 'blue'}[state])


def device():
    clock = Clock()
    display = Display()
    controller = DisplayController(display=display, pages=Pages(), clock=clock, session='boot')
    controller.start()
    return controller, clock, display


def command(op, rid='r1', **params):
    return {'version': 1, 'request_id': rid, 'session': 'boot', 'operation': op, 'params': params}
