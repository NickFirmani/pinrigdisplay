"""One rig service: booth, source observations, USB delivery and tap receipts."""
import argparse
from importlib.resources import files
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit
from shared.display_contracts.commands import MAX_FRAME, error_response, identifier
from shared.http import HTTPServer, JSONHandler
from shared.jobs import Jobs
from shared.rig_api import OBS_REPORT_PATH, parse_obs_report
from shared.release_manifests.display import validate_release
from .authority import Authority
from .command_errors import COMMAND_ERROR_CODES
from .firmware_install import FirmwareInstaller
from . import videonode

LOGGER = logging.getLogger(__name__)


def accept_obs(authority, value: object) -> None:
    """Stamp remote observations with the rig's clock, never a remote monotonic time."""
    live, valid_for = parse_obs_report(value, authority.rig)
    authority.observe_obs(live, valid_for)


def make_rig_handler(authority, *, maintenance=None):
    class Handler(JSONHandler):
        def do_GET(self):
            if self.path == '/':
                body = files(__package__).joinpath('booth.html').read_bytes()
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
            elif self.path == '/healthz':
                self.send_json(200, {'process': 'running'})
            else:
                self.send_json(404, error_response(None, 'not_found', 'route not found'))

        def do_POST(self):
            if self.path not in (OBS_REPORT_PATH, '/api/messages', '/api/clear', '/api/firmware',
                                 '/api/test-state'):
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
                if self.path == '/api/test-state':
                    if not isinstance(value, dict) or set(value) != {'state'}:
                        raise ValueError('expected test state')
                    reply = authority.set_test_state(value['state'])
                    self.send_json(200, {'ok': True, 'state': value['state'],
                                         'delivery': reply})
                    return
                if self.path == '/api/firmware':
                    if not isinstance(value, dict) or not {'release', 'clean'} <= set(value) or set(value) - {'release', 'clean', 'runtime'} or type(value['clean']) is not bool or type(value.get('runtime', False)) is not bool:
                        raise ValueError('expected release and clean boolean')
                    release = identifier(value['release'], 'release')
                    directory = maintenance['releases'] / release
                    if directory.resolve().parent != maintenance['releases'].resolve():
                        raise ValueError('invalid release directory')
                    validate_release(directory)
                    self.send_json(202, maintenance['jobs'].start(lambda phase: maintenance['installer'].install(directory, phase, clean=value['clean'], runtime=value.get('runtime', False))))
                    return
                if self.path == OBS_REPORT_PATH:
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
                self.send_json(200 if reply['ok'] else COMMAND_ERROR_CODES.get(reply['error']['code'], 503), reply)
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
                credentials: str = '', maintenance=None, server_factory=HTTPServer,
                thread_factory=threading.Thread) -> None:
    """Own the listener, workers and USB host, including partial-startup cleanup."""
    server = None
    workers = []
    try:
        server = server_factory((bind, port), make_rig_handler(authority, maintenance=maintenance))
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
                        default=Path('/var/lib/pinrig-rig/interactions.sqlite3'))
    parser.add_argument('--videonode-url', default='http://127.0.0.1:8090')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=48194)
    parser.add_argument('--releases', type=Path, default=Path('/var/lib/pinrig-rig/releases'))
    parser.add_argument('--bootsel-mount', type=Path)
    args = parser.parse_args()
    import serial
    from rig.display_host.interactions import InteractionStore
    from rig.display_host.client import LocalClient
    from rig.display_host.delivery import SerialDelivery
    from rig.display_host.service import Host
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    host = Host(SerialDelivery(lambda: serial.Serial(
        args.serial, 115200, timeout=.1, write_timeout=1)),
        interactions=InteractionStore(args.interactions, capacity=10000))
    authority = Authority(args.rig, LocalClient(host))
    args.releases.mkdir(parents=True, exist_ok=True)
    maintenance = {'jobs': Jobs(args.interactions.parent / 'maintenance.json'), 'installer': FirmwareInstaller(host, args.serial, lock_path=args.interactions.parent / 'maintenance.lock', bootsel_mount=args.bootsel_mount), 'releases': args.releases}
    run_service(authority, host, stop, bind=args.bind, port=args.port,
                videonode_url=args.videonode_url,
                credentials=os.environ.get('VIDEONODE_CREDENTIALS', ''), maintenance=maintenance)


if __name__ == '__main__':
    main()
