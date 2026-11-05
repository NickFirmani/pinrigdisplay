"""Per-rig booth website, OBS ingress, videonode adapter and state authority."""
import argparse
import hmac
from importlib.resources import files
import json
import logging
import os
import signal
import threading
from urllib.parse import urlsplit
from pinrig_protocol.commands import MAX_FRAME, number
from pinrig_protocol.http import CODES, HTTPServer, make_handler
from .authority import Authority, OBS_VALID_FOR
from .client import Client
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


def make_rig_handler(authority, *, token: str = ''):
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
            elif self.path == '/api/status':
                try:
                    self.send_json(200, authority.status())
                except (OSError, ValueError) as error:
                    self.send_json(503, {'error': str(error)})
            else:
                super().do_GET()

        def do_POST(self):
            if self.path not in ('/api/obs', '/api/messages', '/api/clear'):
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
                if self.path == '/api/obs':
                    accept_obs(authority, value)
                    reply = {'ok': True}
                elif self.path == '/api/messages':
                    if not isinstance(value, dict) or set(value) != {'body', 'request_id'}:
                        raise ValueError('expected body and request_id')
                    reply = authority.message(value['body'], value['request_id'])
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


def publish_loop(authority, stop) -> None:
    while not stop.is_set():
        try:
            reply = authority.publish()
            if not reply['ok']:
                LOGGER.warning('State delivery failed: %s', reply)
        except (OSError, ValueError) as error:
            LOGGER.warning('State delivery unavailable: %s', error)
        stop.wait(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rig', choices=('rig1', 'rig2'), required=True)
    parser.add_argument('--host-url', default='http://127.0.0.1:48193')
    parser.add_argument('--videonode-url', default='http://127.0.0.1:8090')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=48194)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    authority = Authority(args.rig, Client(args.host_url, timeout=2))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    server = HTTPServer((args.bind, args.port), make_rig_handler(
        authority, token=os.environ.get('PINRIG_OBS_TOKEN', '')))
    LOGGER.info('%s booth service listening on http://%s:%s', args.rig, args.bind, args.port)
    workers = [threading.Thread(target=server.serve_forever),
               threading.Thread(target=publish_loop, args=(authority, stop)),
               threading.Thread(target=videonode.run, args=(args.videonode_url, authority, stop),
                   kwargs={'credentials': os.environ.get('VIDEONODE_CREDENTIALS', '')})]
    try:
        for worker in workers:
            worker.start()
        stop.wait()
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for worker in workers:
            if worker.ident is not None:
                worker.join()


if __name__ == '__main__':
    main()
