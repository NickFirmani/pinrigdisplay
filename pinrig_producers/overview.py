"""Stream-PC overview: independent rig polling, OBS diagnostics and deployment."""
import argparse
from copy import deepcopy
import hmac
from importlib.resources import files
import json
import logging
import math
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit
from pinrig_protocol.commands import identifier
from pinrig_protocol.http import HTTPServer, make_handler
from . import obs
from .identity import software_identity
from .net import request_json
from .maintenance import Jobs


def load_config(path: Path) -> dict:
    """Read explicit targets and scene mappings; credentials stay in environment."""
    config = json.loads(path.read_text())
    if not isinstance(config, dict):
        raise ValueError('configuration must be an object')
    rigs = config.get('rigs')
    if not isinstance(rigs, list) or not 1 <= len(rigs) <= 32:
        raise ValueError('configure between 1 and 32 rigs')
    seen = set()
    for rig in rigs:
        if not isinstance(rig, dict) or not isinstance(rig.get('url'), str) or 'id' not in rig:
            raise ValueError('each rig needs an id and URL')
        identifier(rig['id'], 'rig ID')
        if rig['id'] in seen:
            raise ValueError('duplicate rig ID')
        seen.add(rig['id'])
        url = urlsplit(rig['url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('rig URL must be HTTP(S), without credentials/query/fragment')
        if not isinstance(rig.get('scenes'), list) or not all(isinstance(s, str) and s for s in rig['scenes']):
            raise ValueError('each rig needs a scenes list')
    return config


class Status:
    def __init__(self, rigs, *, clock=time.monotonic):
        self.rigs, self.clock = rigs, clock
        self.software = software_identity()
        self.lock = threading.Lock()
        self.obs = {'connected': False, 'error': 'No OBS observation'}
        self.obs_at = None
        self.obs_attempt_at = None
        self.delivery = {}
        self.reports = {}

    def observed(self, value: dict) -> None:
        with self.lock:
            self.obs = dict(value)
            self.obs_attempt_at = self.clock()
            if value.get('connected'):
                self.obs_at = self.clock()

    def delivered(self, rig: str, error: str | None) -> None:
        with self.lock:
            self.delivery[rig] = {'error': error, 'at': self.clock()}

    def poll(self, rig: dict, *, get=request_json) -> None:
        try:
            value = get(rig['url'].rstrip('/') + '/api/status')
            if not isinstance(value, dict) or value.get('rig') != rig['id'] or value.get('status_schema') != 1:
                raise ValueError('incompatible or wrong-rig status')
            if not isinstance(value.get('sources', {}), dict):
                raise ValueError('invalid sources status')
            for source in value.get('sources', {}).values():
                if (not isinstance(source, dict) or type(source.get('age')) not in (int, float)
                        or not math.isfinite(source['age']) or source['age'] < 0
                        or type(source.get('fresh')) is not bool
                        or any(source.get(key) is not None and type(source[key]) is not bool for key in ('live', 'active'))):
                    raise ValueError('invalid source status')
            with self.lock:
                self.reports[rig['id']] = {'value': value, 'at': self.clock(), 'error': None}
        except (OSError, ValueError) as error:
            with self.lock:
                self.reports.setdefault(rig['id'], {}).update(error=str(error))

    def snapshot(self) -> dict:
        with self.lock:
            now = self.clock()
            result = {'status_schema': 1, **self.software, 'obs': deepcopy(self.obs), 'rigs': []}
            result['obs']['age'] = None if self.obs_at is None else max(0., now - self.obs_at)
            result['obs']['stale'] = self.obs_at is None or now - self.obs_at > 8 or not self.obs.get('connected')
            for rig in self.rigs:
                report = self.reports.get(rig['id'], {})
                age = None if 'at' not in report else max(0., now - report['at'])
                delivery = self.delivery.get(rig['id'], {})
                result['rigs'].append({'id': rig['id'], 'url': rig['url'], 'age': age,
                    'stale': age is None or age > 6 or bool(report.get('error')),
                    'error': report.get('error'), 'status': deepcopy(report.get('value')),
                    'delivery': {'error': delivery.get('error'), 'age': None if 'at' not in delivery else max(0., now - delivery['at'])}})
            return result


def handler(status, jobs, deploy, token):
    class Handler(make_handler(status)):
        def do_GET(self):
            if self.path == '/':
                body = files('pinrig_producers').joinpath('overview.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            elif self.path == '/api/status':
                self.send_json(200, {**status.snapshot(), 'maintenance': jobs.status()})
            else:
                self.send_json(404, {'error': 'route not found'})

        def do_POST(self):
            if self.path != '/api/install':
                self.send_json(404, {'error': 'route not found'})
                return
            if not token or not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
                self.send_json(403, {'error': 'maintenance credential required'})
                return
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                self.send_json(403, {'error': 'cross-origin request rejected'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json' or not 0 < length <= 8192:
                    raise ValueError('use bounded application/json')
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict) or set(value) != {'rig', 'release'}:
                    raise ValueError('expected rig and release')
                identifier(value['release'], 'release')
                rig = next((r for r in status.rigs if r['id'] == value['rig']), None)
                if rig is None:
                    raise ValueError('unknown rig')
                action = deploy(rig, value['release'])
                self.send_json(202, jobs.start(action))
            except (ValueError, OSError) as error:
                self.send_json(422, {'error': str(error)})
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=48195)
    parser.add_argument('--state', type=Path, default=Path('/var/lib/pinrig-stream'))
    parser.add_argument('--releases', type=Path, default=Path('/var/lib/pinrig-stream/releases'))
    args = parser.parse_args()
    config = load_config(args.config)
    logging.basicConfig(level=logging.INFO)
    status = Status(config['rigs'])
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    jobs = Jobs(args.state / 'maintenance.json')
    from .deployment import deployment_action
    def deploy(rig, release):
        directory = args.releases / release
        if directory.resolve().parent != args.releases.resolve():
            raise ValueError('invalid release')
        return deployment_action(rig, directory, token=os.environ.get('PINRIG_MAINTENANCE_TOKEN', ''))
    server = HTTPServer((args.bind, args.port), handler(status, jobs, deploy, os.environ.get('PINRIG_MAINTENANCE_TOKEN', '')))
    targets = {r['id']: r['url'] for r in config['rigs']}
    mappings = {r['id']: r['scenes'] for r in config['rigs']}
    def poll(rig):
        while not stop.is_set():
            status.poll(rig)
            stop.wait(2)
    workers = [threading.Thread(target=server.serve_forever), threading.Thread(target=obs.run,
        args=(targets, stop), kwargs={'url': config.get('obs_url', 'ws://127.0.0.1:4455'),
        'password': os.environ.get('OBS_WEBSOCKET_PASSWORD', ''), 'token': os.environ.get('PINRIG_OBS_TOKEN', ''),
        'status': status, 'mappings': mappings})]
    workers += [threading.Thread(target=poll, args=(rig,)) for rig in config['rigs']]
    try:
        for worker in workers:
            worker.start()
        while not stop.wait(.5):
            pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for worker in workers:
            if worker.ident is not None:
                worker.join()
        jobs.wait()
