"""Twitch device authorization, persistent settings and EventSub lifecycle."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import websocket

from shared.net import read_json

OAUTH = 'https://id.twitch.tv/oauth2/'
HELIX = 'https://api.twitch.tv/helix/'
EVENTSUB = 'wss://eventsub.wss.twitch.tv/ws'
SCOPE = 'user:read:chat'
DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'
VALIDATE_SECONDS = 3600


class TwitchError(OSError):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(f'Twitch returned HTTP {status}')


def request(url, *, form=None, value=None, headers=None):
    headers = dict(headers or {})
    body = None
    if form is not None:
        if url == OAUTH + 'device' or form.get('grant_type') == DEVICE_GRANT:
            boundary = uuid4().hex
            body = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                           f'{item}\r\n' for key, item in form.items()).encode()
            body += f'--{boundary}--\r\n'.encode()
            headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
        else:
            body = urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if value is not None:
        body = json.dumps(value).encode()
        headers['Content-Type'] = 'application/json'
    try:
        with urlopen(Request(url, body, headers), timeout=5) as response:
            return read_json(response)
    except HTTPError as error:
        with error:
            try:
                message = read_json(error).get('message')
            except (ValueError, AttributeError):
                message = None
        raise TwitchError(error.code, message) from None


def save(path: Path, value: dict) -> None:
    """Replace a complete state file with permissions set before writing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def twitch_url(url: str, scheme: str, hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != scheme or parsed.netloc not in hosts:
        raise ValueError('unexpected Twitch URL')
    return url


class LiveState:
    """Keep observed online/offline events ahead of a reconciliation snapshot."""
    def __init__(self):
        self.value = None
        self.timestamp = ''

    def event(self, live: bool, timestamp: str) -> None:
        if timestamp > self.timestamp:
            self.value, self.timestamp = live, timestamp

    def reconcile(self, live: bool) -> None:
        if not self.timestamp:
            self.value = live


class Twitch:
    def __init__(self, client_id: str, state: Path, chat, *, clock=time.monotonic,
                 http=request, connect=websocket.create_connection):
        self.client_id, self.chat, self.clock = client_id, chat, clock
        self.http, self.connect = http, connect
        self.settings_path = state / 'twitch.json'
        self.auth_path = state / 'twitch-auth.json'
        self.settings = load(self.settings_path)
        self.auth = load(self.auth_path) if client_id else {}
        if self.auth.get('client_id') != client_id:
            self.auth = {}
        self.lock = threading.Lock()
        self.generation = 0
        self.device = None
        self.live = None
        self.connection = 'Disconnected'
        self.error = None
        for rig_id in chat.targets:
            chat.enable(rig_id, self.settings.get('rigs', {}).get(rig_id, True))

    def snapshot(self) -> dict:
        with self.lock:
            device = self.device if self.device and self.clock() < self.device['expires'] else None
            return {'configured': bool(self.client_id), 'channel': self.auth.get('login'),
                    'live': self.live, 'connection': self.connection, 'error': self.error,
                    'verification': ({key: device[key] for key in ('verification_uri', 'user_code')}
                                     if device else None),
                    'rigs': dict(self.settings.get('rigs', {}))}

    def _status(self, connection, live=None, error=None):
        self.connection, self.live, self.error = connection, live, error
        self.chat.channel(bool(self.auth), live)

    def _disconnect(self):
        # The credential file is authoritative on restart.
        self.auth_path.unlink(missing_ok=True)
        self.generation += 1
        self.auth, self.device = {}, None
        self._status('Disconnected')
        updated = {'rigs': self.settings.get('rigs', {})}
        save(self.settings_path, updated)
        self.settings = updated

    def action(self, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError('expected a Twitch action')
        action = value.get('action')
        if action == 'toggle' and set(value) == {'action', 'rig', 'enabled'}:
            rig_id, enabled = value['rig'], value['enabled']
            if not isinstance(rig_id, str) or rig_id not in self.chat.targets or type(enabled) is not bool:
                raise ValueError('expected configured rig and enabled boolean')
            with self.lock:
                updated = {**self.settings, 'rigs': {**self.settings.get('rigs', {}), rig_id: enabled}}
                save(self.settings_path, updated)
                self.settings = updated
                self.chat.enable(rig_id, enabled)
        elif action == 'test' and set(value) == {'action', 'rig'}:
            if not isinstance(value['rig'], str) or value['rig'] not in self.chat.targets:
                raise ValueError('unknown rig')
            self.chat.test(value['rig'])
        elif action == 'disconnect' and set(value) == {'action'}:
            with self.lock:
                self._disconnect()
        elif action in ('connect', 'change') and set(value) == {'action'}:
            if not self.client_id:
                raise ValueError('Set twitch_client_id in the stream PC config first.')
            with self.lock:
                if action == 'connect' and self.auth:
                    raise ValueError('Twitch is already connected.')
                if self.device and self.clock() < self.device['expires']:
                    return {'ok': True}
                self.device = None
                if action == 'change':
                    self._disconnect()
                generation = self.generation
            device = self.http(OAUTH + 'device', form={'client_id': self.client_id, 'scopes': SCOPE})
            try:
                twitch_url(device['verification_uri'], 'https', ('www.twitch.tv', 'twitch.tv'))
                now = self.clock()
                interval = max(1, int(device['interval']))
                device.update(expires=now + int(device['expires_in']), interval=interval,
                              poll_at=now + interval)
                if not all(isinstance(device[key], str) and device[key] for key in ('user_code', 'device_code')):
                    raise ValueError('invalid verification code')
            except (KeyError, TypeError, ValueError):
                raise OSError('Twitch returned invalid device authorization details') from None
            with self.lock:
                if generation == self.generation and self.device is None:
                    self.device = device
                    self._status('Waiting for Twitch approval')
        else:
            raise ValueError('invalid Twitch action')
        return {'ok': True}

    def _validate(self, token):
        result = self.http(OAUTH + 'validate', headers={'Authorization': 'OAuth ' + token})
        if (result.get('client_id') != self.client_id or SCOPE not in result.get('scopes', [])
                or not result.get('user_id') or not result.get('login')):
            raise ValueError('Twitch token is missing its broadcaster or chat permission')
        return result

    def _record_auth(self, token, identity, generation):
        auth = {'client_id': self.client_id, 'access_token': token['access_token'],
                'refresh_token': token['refresh_token'], 'user_id': identity['user_id'],
                'login': identity['login'],
                'expires_at': time.time() + int(identity['expires_in'])}
        with self.lock:
            if generation != self.generation:
                return None
            settings = {**self.settings, 'channel': {'id': auth['user_id'], 'login': auth['login']}}
            save(self.settings_path, settings)
            save(self.auth_path, auth)
            self.auth, self.settings, self.device = auth, settings, None
            self._status('Connecting')
        return auth

    def _poll_device(self, device, generation):
        now = self.clock()
        with self.lock:
            if generation != self.generation or device is not self.device:
                return
            if now >= device['expires']:
                self.device = None
                self._status('Disconnected', error='Twitch approval code expired.')
                return
            if now < device['poll_at']:
                return
            device['poll_at'] = now + device['interval']
        try:
            token = self.http(OAUTH + 'token', form={
                'client_id': self.client_id, 'scopes': SCOPE, 'device_code': device['device_code'],
                'grant_type': DEVICE_GRANT})
        except TwitchError as error:
            with self.lock:
                if generation != self.generation or device is not self.device:
                    return
                if error.message == 'slow_down':
                    device['interval'] += 5
                    device['poll_at'] = now + device['interval']
                elif error.message != 'authorization_pending':
                    if error.status >= 500 or error.status == 429:
                        raise
                    self.device = None
                    self._status('Disconnected', error='Twitch approval failed. Connect again.')
            return
        self._record_auth(token, self._validate(token['access_token']), generation)

    def _credentials(self, auth, generation):
        try:
            identity = self._validate(auth['access_token'])
        except TwitchError as error:
            if error.status != 401 or time.time() < auth['expires_at'] - 120:
                raise
        else:
            if identity['user_id'] != auth['user_id']:
                raise ValueError('Twitch broadcaster changed')
            if int(identity['expires_in']) > 120:
                return auth, min(VALIDATE_SECONDS, int(identity['expires_in']) - 120)
        refreshed = self.http(OAUTH + 'token', form={'client_id': self.client_id,
                              'grant_type': 'refresh_token', 'refresh_token': auth['refresh_token']})
        # The old refresh token is single-use. Persist its replacement before further HTTP.
        identity = {'user_id': auth['user_id'], 'login': auth['login'], 'expires_in': refreshed['expires_in']}
        auth = self._record_auth(refreshed, identity, generation)
        if auth:
            validated = self._validate(auth['access_token'])
            if validated['user_id'] != auth['user_id']:
                raise ValueError('Twitch broadcaster changed')
        return auth, min(VALIDATE_SECONDS, max(1, int(refreshed['expires_in']) - 120))

    def _welcome(self, url):
        socket = self.connect(url, timeout=5, enable_multithread=True)
        try:
            message = json.loads(socket.recv())
            if message['metadata']['message_type'] != 'session_welcome':
                raise ValueError('missing Twitch session welcome')
            session = message['payload']['session']
            socket.settimeout(.5)
            return socket, session
        except Exception:
            socket.close(timeout=0)
            raise

    def _session(self, auth, generation, stop, validate_after):
        headers = {'Client-Id': self.client_id, 'Authorization': 'Bearer ' + auth['access_token']}
        user_id = auth['user_id']
        socket, session = self._welcome(EVENTSUB)
        state = LiveState()
        try:
            for kind in ('channel.chat.message', 'stream.online', 'stream.offline'):
                condition = {'broadcaster_user_id': user_id}
                if kind == 'channel.chat.message':
                    condition['user_id'] = user_id
                self.http(HELIX + 'eventsub/subscriptions', headers=headers, value={
                    'type': kind, 'version': '1', 'condition': condition,
                    'transport': {'method': 'websocket', 'session_id': session['id']}})
            with ThreadPoolExecutor(max_workers=1) as executor:
                live_request = executor.submit(self.http, HELIX + 'streams?' + urlencode({'user_id': user_id}),
                                               headers=headers)
                try:
                    self._listen(socket, session, live_request, state, auth, generation, stop, validate_after)
                except Exception:
                    with self.lock:
                        if generation == self.generation:
                            self._status('Reconnecting')
                    raise
        finally:
            socket.close(timeout=0)

    def _listen(self, socket, session, live_request, state, auth, generation, stop, validate_after):
        deadline = self.clock() + session['keepalive_timeout_seconds']
        original = socket
        try:
            while not stop.is_set():
                with self.lock:
                    if generation != self.generation:
                        return
                if self.clock() >= validate_after:
                    current, validate_in = self._credentials(auth, generation)
                    if current is not auth:
                        return
                    validate_after = self.clock() + validate_in
                try:
                    raw = socket.recv()
                except websocket.WebSocketTimeoutException:
                    if self.clock() >= deadline:
                        raise OSError('Twitch chat keepalive expired') from None
                    raw = None
                if raw == '':
                    raise OSError('Twitch closed the chat connection')
                if raw is not None:
                    packet = json.loads(raw)
                    metadata, payload = packet['metadata'], packet['payload']
                    deadline = self.clock() + session['keepalive_timeout_seconds']
                    kind = metadata['message_type']
                    if kind == 'session_reconnect':
                        url = twitch_url(payload['session']['reconnect_url'], 'wss', ('eventsub.wss.twitch.tv',))
                        replacement, session = self._welcome(url)
                        socket.close(timeout=0)
                        socket = replacement
                        deadline = self.clock() + session['keepalive_timeout_seconds']
                    elif kind == 'revocation':
                        raise TwitchError(401, 'subscription revoked')
                    elif kind == 'notification':
                        with self.lock:
                            if generation != self.generation:
                                return
                            self._notification(metadata, payload, state)
                if live_request is not None and live_request.done():
                    state.reconcile(bool(live_request.result()['data']))
                    live_request = None
                    with self.lock:
                        if generation != self.generation:
                            return
                        self._status('Connected', state.value)
        finally:
            if socket is not original:
                socket.close(timeout=0)

    def _notification(self, metadata, payload, state):
        kind, event = metadata['subscription_type'], payload['event']
        if kind in ('stream.online', 'stream.offline'):
            state.event(kind == 'stream.online', metadata['message_timestamp'])
            self._status('Connected', state.value)
        elif kind == 'channel.chat.message':
            self.chat.receive(metadata['message_id'], event['chatter_user_id'],
                              event['chatter_user_name'], event['message']['text'])

    def run(self, stop: threading.Event):
        retry = 1
        while not stop.is_set():
            with self.lock:
                auth, device, generation = self.auth, self.device, self.generation
            try:
                if device:
                    self._poll_device(device, generation)
                elif auth:
                    auth, validate_in = self._credentials(auth, generation)
                    if auth:
                        self._session(auth, generation, stop, self.clock() + validate_in)
                        with self.lock:
                            if generation == self.generation:
                                self._status('Connecting')
                retry = 1
                stop.wait(.5)
            except (OSError, websocket.WebSocketException, ValueError, KeyError, TypeError) as error:
                with self.lock:
                    if generation != self.generation:
                        continue
                    if auth and isinstance(error, TwitchError) and error.status in (400, 401, 403):
                        try:
                            self._disconnect()
                        except OSError:
                            self._status('Disconnected', error='Could not remove Twitch credentials.')
                        else:
                            self._status('Disconnected', error='Twitch authorization expired or was revoked. Connect again.')
                    else:
                        self._status('Reconnecting' if auth else 'Waiting for Twitch approval',
                                     error='Twitch request failed. Retrying.')
                stop.wait(retry)
                retry = min(30, retry * 2)
