"""Stream-PC overview: independent rig polling, OBS diagnostics and deployment."""
import argparse
from copy import deepcopy
from importlib.resources import files
import json
import logging
import math
import os
from pathlib import Path
import signal
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from shared.display_contracts.commands import Command, identifier
from shared.http import HTTPServer, JSONHandler
from . import obs
from .chat import Chat
from .twitch import Twitch
from shared.identity import software_identity
from shared.net import read_json, request_json
from shared.jobs import Jobs


def load_config(path: Path) -> dict:
    """Read explicit targets and scene mappings; credentials stay in environment."""
    config = json.loads(path.read_text())
    if not isinstance(config, dict):
        raise ValueError('configuration must be an object')
    client_id = config.get('twitch_client_id', '')
    if client_id != '':
        identifier(client_id, 'Twitch client ID')
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
    def __init__(self, rigs, *, clock=time.monotonic, nickname_path: Path | None = None):
        self.rigs, self.clock = rigs, clock
        self.software = software_identity('pinrig-stream')
        self.lock = threading.Lock()
        self.obs = {'connected': False, 'error': 'No OBS observation'}
        self.obs_at = None
        self.obs_attempt_at = None
        self.delivery = {}
        self.reports = {}
        self.nickname_path = nickname_path
        self.nicknames = (json.loads(nickname_path.read_text())
                          if nickname_path is not None and nickname_path.exists() else {})

    def set_nickname(self, rig: str, nickname: str) -> str:
        """Store a nickname by configured rig ID. An empty nickname clears it."""
        if not any(target['id'] == rig for target in self.rigs):
            raise ValueError('unknown rig')
        if not isinstance(nickname, str):
            raise ValueError('nickname must be text')
        nickname = nickname.strip()
        if len(nickname) > 40 or (nickname and not nickname.isprintable()):
            raise ValueError('nickname must contain at most 40 printable characters')
        with self.lock:
            updated = dict(self.nicknames)
            if nickname:
                updated[rig] = nickname
            else:
                updated.pop(rig, None)
            if self.nickname_path is not None:
                self.nickname_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.nickname_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(updated))
                temporary.replace(self.nickname_path)
            self.nicknames = updated
        return nickname

    def observed(self, value: dict) -> None:
        with self.lock:
            self.obs = dict(value)
            self.obs_attempt_at = self.clock()
            if value.get('connected'):
                self.obs_at = self.clock()

    def delivered(self, rig: str, error: str | None) -> None:
        with self.lock:
            self.delivery[rig] = {'error': error, 'at': self.clock()}

    def poll(self, rig: dict, *, get=request_json) -> dict:
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
            return value
        except (OSError, ValueError) as error:
            with self.lock:
                self.reports.setdefault(rig['id'], {}).update(error=str(error))
            return {}

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
                    'nickname': self.nicknames.get(rig['id'], ''),
                    'stale': age is None or age > 6 or bool(report.get('error')),
                    'error': report.get('error'), 'status': deepcopy(report.get('value')),
                    'delivery': {'error': delivery.get('error'), 'age': None if 'at' not in delivery else max(0., now - delivery['at'])}})
            return result


def forward_message(rig: dict, payload: dict) -> tuple[int, dict]:
    """Preserve the rig's application response, including display rejections."""
    request = Request(rig['url'].rstrip('/') + '/api/messages',
                      json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        result = read_json(response)
        if not isinstance(result, dict):
            raise OSError('Invalid rig message response')
        return response.status, result


def handler(status, jobs, deploy, test_display=None, *, send_message=forward_message, twitch=None):
    class Handler(JSONHandler):
        def do_GET(self):
            if self.path == '/':
                body = files(__package__).joinpath('overview.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            elif self.path == '/api/status':
                payload = {**status.snapshot(), 'maintenance': jobs.status()}
                if twitch is not None:
                    payload['twitch'] = twitch.snapshot()
                    for rig in payload['rigs']:
                        rig['chat_delivery'] = twitch.chat.outcome(rig['id'])
                self.send_json(200, payload)
            else:
                self.send_json(404, {'error': 'route not found'})

        def do_POST(self):
            if self.path not in ('/api/install', '/api/test-state', '/api/messages', '/api/nickname', '/api/twitch'):
                self.send_json(404, {'error': 'route not found'})
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
                if self.path == '/api/twitch':
                    if twitch is None:
                        raise ValueError('Twitch chat is unavailable.')
                    self.send_json(200, twitch.action(value))
                    return
                if self.path == '/api/nickname':
                    if not isinstance(value, dict) or set(value) != {'rig', 'nickname'}:
                        raise ValueError('expected rig and nickname')
                    nickname = status.set_nickname(value['rig'], value['nickname'])
                    self.send_json(200, {'nickname': nickname})
                    return
                if self.path == '/api/messages':
                    if not isinstance(value, dict) or set(value) != {
                            'rig', 'title', 'body', 'duration', 'requires_ack', 'request_id'}:
                        raise ValueError('expected rig and message fields')
                    rig = next((r for r in status.rigs if r['id'] == value['rig']), None)
                    if rig is None:
                        raise ValueError('unknown rig')
                    request_id = value['request_id']
                    params = {key: value[key] for key in ('title', 'body', 'duration', 'requires_ack')}
                    params['priority'] = 8
                    command = Command.parse({'version': 1, 'request_id': request_id,
                                             'session': 'validate', 'operation': 'show_message',
                                             'params': params})
                    try:
                        code, reply = send_message(rig, {**command.params, 'request_id': request_id})
                    except (OSError, ValueError):
                        self.send_json(502, {'error': 'Could not confirm delivery to the rig.'})
                    else:
                        self.send_json(code, reply)
                    return
                if self.path == '/api/test-state':
                    if (test_display is None or not isinstance(value, dict)
                            or set(value) != {'rig', 'state'}):
                        raise ValueError('expected rig and test state')
                    rig = next((r for r in status.rigs if r['id'] == value['rig']), None)
                    if rig is None:
                        raise ValueError('unknown rig')
                    self.send_json(200, test_display(rig, value['state']))
                    return
                if not isinstance(value, dict) or set(value) != {'rig', 'release'}:
                    raise ValueError('expected rig and release')
                identifier(value['release'], 'release')
                rig = next((r for r in status.rigs if r['id'] == value['rig']), None)
                if rig is None:
                    raise ValueError('unknown rig')
                action = deploy(rig, value['release'])
                self.send_json(202, jobs.start(action))
            except ValueError as error:
                self.send_json(422, {'error': str(error)})
            except OSError as error:
                self.send_json(503, {'error': str(error)})
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
    status = Status(config['rigs'], nickname_path=args.state / 'nicknames.json')
    chat = Chat(config['rigs'])
    twitch = Twitch(config.get('twitch_client_id', ''), args.state, chat)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    jobs = Jobs(args.state / 'maintenance.json')
    from .deployment import deployment_action
    def deploy(rig, release):
        directory = args.releases / release
        if directory.resolve().parent != args.releases.resolve():
            raise ValueError('invalid release')
        return deployment_action(rig, directory)
    def test_display(rig, state):
        return request_json(rig['url'].rstrip('/') + '/api/test-state', {'state': state})
    server = HTTPServer((args.bind, args.port),
                        handler(status, jobs, deploy, test_display, twitch=twitch))
    targets = {r['id']: r['url'] for r in config['rigs']}
    mappings = {r['id']: r['scenes'] for r in config['rigs']}
    def poll(rig):
        while not stop.is_set():
            report = status.poll(rig)
            chat_status = report.get('chat')
            chat.report(rig['id'], chat_status if isinstance(chat_status, dict) else {})
            stop.wait(2)
    workers = [threading.Thread(target=server.serve_forever), threading.Thread(target=obs.run,
        args=(targets, stop), kwargs={'url': config.get('obs_url', 'ws://127.0.0.1:4455'),
        'password': os.environ.get('OBS_WEBSOCKET_PASSWORD', ''),
        'status': status, 'mappings': mappings})]
    workers += [threading.Thread(target=poll, args=(rig,)) for rig in config['rigs']]
    if twitch.client_id:
        workers.append(threading.Thread(target=twitch.run, args=(stop,)))
        workers.extend(threading.Thread(target=chat.run_rig, args=(rig, stop)) for rig in config['rigs'])
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


if __name__ == '__main__':
    main()
