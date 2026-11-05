"""Independent host executable. Serial paths should use /dev/serial/by-id/."""
import argparse
from pathlib import Path
from pinrig_protocol.interactions import InteractionStore
import logging
import signal
import threading
from pinrig_protocol.http import create_server
from .delivery import SerialDelivery
from .service import Host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--interactions', type=Path, default=Path('/var/lib/pinrig-host/interactions.sqlite3'))
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=48193)
    args = parser.parse_args()
    import serial
    logging.basicConfig(level=logging.INFO)
    host = Host(SerialDelivery(lambda: serial.Serial(args.serial, 115200, timeout=.1, write_timeout=1)),
                interactions=InteractionStore(args.interactions, capacity=10000))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    server = None
    worker = None
    try:
        server = create_server(args.bind, args.port, host)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        while not stop.is_set():
            host.tick()
            stop.wait(.5)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join()
        host.close()


if __name__ == '__main__':
    main()
