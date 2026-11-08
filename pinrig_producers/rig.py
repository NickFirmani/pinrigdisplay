"""One rig service: booth, source observations, USB delivery and tap receipts."""
import argparse
import hmac
from importlib.resources import files
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit
from pinrig_protocol.commands import MAX_FRAME, number
from pinrig_protocol.http import CODES, HTTPServer, make_handler
from .authority import Authority, OBS_VALID_FOR
from . import videonode

LOGGER = logging.getLogger(__name__)


def accept_obs(authority, value: object) -> None:
    """Stamp remote observations with the rig's clock, never a remote monotonic time."""
    if (not isinstance(value, dict) or set(value) != {'rig', 'live', 'valid_for'}
            or value['rig'] != authority.rig):
        raise ValueError('OBS report must target this rig with rig, live and valid_for')
    live = value['live']
    if live is not None and type(live) is not bool:
        raise ValueError('live must be true, false or null')
    valid_for = number(value['valid_for'], 'valid_for', .001, OBS_VALID_FOR)
    authority.observe_obs(live, valid_for)


def make_rig_handler(authority, *, token: str = '', maintenance=None, maintenance_token: str = ''):
    class Handler(make_handler(authority)):
        def do_GET(self):
            if self.path == '/':
                body = files('pinrig_producers').joinpath('booth.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
            elif self.path == '/api/maintenance' and maintenance:
                self.send_json(200, maintenance['jobs'].status())
            elif self.path == '/api/releases' and maintenance:
                self.send_json(200, {'releases': sorted(p.name for p in maintenance['releases'].iterdir() if p.is_dir() and (p / 'manifest.json').is_file())})
            elif self.path == '/api/status':
                try:
                    self.send_json(200, authority.status())
                except (OSError, ValueError) as error:
                    self.send_json(503, {'error': str(error)})
            else:
                super().do_GET()

        def do_POST(self):
            if self.path not in ('/api/obs', '/api/messages', '/api/clear', '/api/firmware'):
                self.send_json(404, {'error': 'route not found'})
                return
            origin = self.headers.get('Origin')
            try:
                same_origin = not origin or urlsplit(origin).netloc == self.headers.get('Host')
            except ValueError:
                same_origin = False
            if not same_origin:
                self.send_json(403, {'error': 'cross-origin requests are not accepted'})
                return
            if self.path == '/api/firmware' and (not maintenance or not maintenance_token or not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + maintenance_token).encode())):
                self.send_json(403, {'error': 'configured maintenance credential required'})
                return
            if self.path == '/api/obs' and token and not hmac.compare_digest(
                    self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
                self.send_json(401, {'error': 'OBS token required'})
                return
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                self.send_json(415, {'error': 'use application/json with Content-Length'})
                return
            try:
                length = int(self.headers.get('Content-Length', ''))
                if not 0 < length <= MAX_FRAME:
                    raise ValueError('invalid body size')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('incomplete body')
                value = json.loads(raw)
                if self.path == '/api/firmware':
                    if not isinstance(value, dict) or not {'release', 'clean'} <= set(value) or set(value) - {'release', 'clean', 'runtime'} or type(value['clean']) is not bool or type(value.get('runtime', False)) is not bool:
                        raise ValueError('expected release and clean boolean')
                    from pinrig_protocol.commands import identifier
                    release = identifier(value['release'], 'release')
                    directory = maintenance['releases'] / release
                    if directory.resolve().parent != maintenance['releases'].resolve():
                        raise ValueError('invalid release directory')
                    from .releases import validate_release
                    validate_release(directory)
                    self.send_json(202, maintenance['jobs'].start(lambda phase: maintenance['installer'].install(directory, phase, clean=value['clean'], runtime=value.get('runtime', False))))
                    return
                if self.path == '/api/obs':
                    accept_obs(authority, value)
                    reply = {'ok': True}
                elif self.path == '/api/messages':
                    if (not isinstance(value, dict) or not {'body', 'request_id'} <= set(value)
                            or set(value) - {'body', 'request_id', 'title', 'priority', 'duration', 'requires_ack'}):
                        raise ValueError('expected body, request_id and optional message parameters')
                    reply = authority.message(**value)
                else:
                    if not isinstance(value, dict) or set(value) != {'message_id'}:
                        raise ValueError('expected message_id')
                    reply = authority.clear(value['message_id'])
                self.send_json(200 if reply['ok'] else CODES.get(reply['error']['code'], 503), reply)
            except (ValueError, UnicodeError, RecursionError) as error:
                self.send_json(422, {'error': str(error)})
            except OSError as error:
                self.send_json(503, {'error': str(error)})
    return Handler


def run_delivery(authority, host, stop, *, clock=time.monotonic) -> None:
    """Publish each second and poll USB/receipts between publications."""
    publish_at = clock()
    while not stop.is_set():
        if clock() >= publish_at:
            try:
                reply = authority.publish()
                if not reply['ok']:
                    LOGGER.warning('State delivery failed: %s', reply)
            except (OSError, ValueError) as error:
                LOGGER.warning('State delivery unavailable: %s', error)
            publish_at = clock() + 1
        with authority.sender_lock:
            host.tick()
        stop.wait(.5)


def run_service(authority, host, stop, *, bind: str, port: int, videonode_url: str,
                token: str = '', credentials: str = '', maintenance=None, maintenance_token: str = '', server_factory=HTTPServer,
                thread_factory=threading.Thread) -> None:
    """Own the listener, workers and USB host, including partial-startup cleanup."""
    server = None
    workers = []
    try:
        server = server_factory((bind, port), make_rig_handler(authority, token=token, maintenance=maintenance, maintenance_token=maintenance_token))
        # Drain accepted HTTP work before closing USB, so a late request cannot
        # reopen the serial connection after shutdown.
        server.daemon_threads = False
        workers = [thread_factory(target=server.serve_forever),
                   thread_factory(target=videonode.run, args=(videonode_url, authority, stop),
                                  kwargs={'credentials': credentials})]
        for worker in workers:
            worker.start()
        LOGGER.info('%s rig service listening on http://%s:%s', authority.rig, bind, port)
        run_delivery(authority, host, stop)
    finally:
        stop.set()
        try:
            if server is not None:
                if workers and workers[0].ident is not None:
                    server.shutdown()
                server.server_close()
            for worker in workers:
                if worker.ident is not None:
                    worker.join()
        finally:
            if maintenance:
                maintenance['jobs'].wait()
            host.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rig', required=True)
    parser.add_argument('--serial', required=True, help='stable /dev/serial/by-id/... device path')
    parser.add_argument('--interactions', type=Path,
                        default=Path('/var/lib/pinrig-host/interactions.sqlite3'))
    parser.add_argument('--videonode-url', default='http://127.0.0.1:8090')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=48194)
    parser.add_argument('--releases', type=Path, default=Path('/var/lib/pinrig-host/releases'))
    parser.add_argument('--bootsel-mount', type=Path)
    args = parser.parse_args()
    # Only rig installs need the host/serial extra; the stream-PC OBS generator
    # and --help remain usable without it.
    import serial
    from pinrig_protocol.interactions import InteractionStore
    from pinrig_host.client import LocalClient
    from pinrig_host.delivery import SerialDelivery
    from pinrig_host.service import Host
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    host = Host(SerialDelivery(lambda: serial.Serial(
        args.serial, 115200, timeout=.1, write_timeout=1)),
        interactions=InteractionStore(args.interactions, capacity=10000))
    authority = Authority(args.rig, LocalClient(host))
    from .maintenance import Jobs, FirmwareInstaller
    args.releases.mkdir(parents=True, exist_ok=True)
    maintenance = {'jobs': Jobs(args.interactions.parent / 'maintenance.json'), 'installer': FirmwareInstaller(host, args.serial, lock_path=args.interactions.parent / 'maintenance.lock', bootsel_mount=args.bootsel_mount), 'releases': args.releases}
    run_service(authority, host, stop, bind=args.bind, port=args.port,
                videonode_url=args.videonode_url, token=os.environ.get('PINRIG_OBS_TOKEN', ''),
                credentials=os.environ.get('VIDEONODE_CREDENTIALS', ''), maintenance=maintenance,
                maintenance_token=os.environ.get('PINRIG_MAINTENANCE_TOKEN', ''))


if __name__ == '__main__':
    main()
