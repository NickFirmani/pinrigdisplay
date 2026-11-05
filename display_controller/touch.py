"""XPT2046 pressure-only tap input. No coordinate calibration is needed for any-screen taps."""
import logging
import threading

LOGGER = logging.getLogger(__name__)


class XPT2046:
    def __init__(self, spi=None, *, bus_lock=None):
        self.bus_lock = bus_lock if bus_lock is not None else threading.Lock()
        if spi is None:
            import spidev
            spi = spidev.SpiDev()
        self.spi = spi
        try:
            spi.open(0, 1)
            spi.mode = 0
            spi.max_speed_hz = 100_000
        except Exception:
            spi.close()
            raise

    def pressed(self) -> bool:
        def read(command):
            data = self.spi.xfer2([command, 0, 0])
            return ((data[1] << 8) | data[2]) >> 3
        # A display window command plus its chunked pixel transfer must finish
        # before touch traffic uses the same physical SPI bus.
        with self.bus_lock:
            z1, z2 = read(0xB0), read(0xC0)
        return 100 < z1 < 4095 and 0 < z2 < 4000

    def close(self) -> None:
        self.spi.close()


class TouchWorker:
    def __init__(self, reader, controller):
        self.reader = reader
        self.controller = controller
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name='touch-input', daemon=True)

    def start(self) -> None:
        self.thread.start()

    def run(self) -> None:
        previous = None
        count = 0
        try:
            while not self.stop.is_set():
                pressed = self.reader.pressed()
                count = count + 1 if pressed == previous else 1
                previous = pressed
                if count == 2:
                    self.controller.touch(pressed)
                self.stop.wait(.02)
        except Exception as error:
            LOGGER.exception('Touch input failed')
            self.controller.touch_failed(str(error))
        finally:
            self.reader.close()

    def close(self) -> None:
        self.stop.set()
        self.thread.join()
