"""Single ordered sender, desired-state freshness, reconnect and lease renewal."""
from collections import OrderedDict
from copy import deepcopy
import logging
import threading
import time
import uuid
from pinrig_protocol.commands import Command, CommandError, RETRY_CAPACITY, RETRY_SECONDS, response, error_response


class Host:
    def __init__(self, delivery, *, clock=time.monotonic, interactions=None):
        self.interactions = interactions
        self.interaction_fault = None
        self.delivery = delivery
        self.clock = clock
        self.session = uuid.uuid4().hex
        self.device_session = None
        self.desired = None
        self.fresh_until = 0.
        self.renew_at = 0.
        self.reconnect_at = 0.
        self.backoff = 1.
        self.last_response = None
        self.device_status = None
        self.fault = 'Not connected'
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def _command(self, operation, params=None):
        return {'version': 1, 'request_id': uuid.uuid4().hex, 'session': self.device_session,
                'operation': operation, 'params': params or {}}

    def _exchange(self, command):
        result = self.delivery.exchange(command)
        self.last_response = self.clock()
        return result

    def _connect(self):
        if self.device_session is None:
            hello = self._exchange(self._command('hello'))
            if not hello.get('ok') or not isinstance(hello.get('result', {}).get('session'), str):
                raise OSError('device handshake failed')
            self.device_session = hello['result']['session']
            self.backoff = 1.
            self.fault = None
            self.renew_at = 0.

    def _disconnected(self, error):
        self.fault = str(error)
        logging.getLogger(__name__).warning('Device delivery unavailable: %s', error)
        self.device_session = None
        self.delivery.close()
        self.reconnect_at = self.clock() + self.backoff
        self.backoff = min(30., self.backoff * 2)

    def _renew(self):
        now = self.clock()
        if self.desired and now < self.fresh_until:
            params = dict(self.desired)
            remaining = self.fresh_until - now
            if remaining < 1:
                params = {'state': 'unknown', 'diagnostic': 'Upstream state expired'}
            else:
                params['valid_for'] = remaining
        else:
            params = {'state': 'unknown', 'diagnostic': 'No fresh upstream state'}
        reply = self._exchange(self._command('set_state', params))
        if not reply['ok']:
            raise OSError(f"state renewal failed: {reply['error']}")
        self.renew_at = now + min(params.get('lease_seconds', 15), params.get('valid_for', 30)) / 3

    def tick(self) -> None:
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.device_session is None and self.clock() < self.reconnect_at:
                return
            self._connect()
            if self.clock() >= self.renew_at:
                self._renew()
            reply = self._exchange(self._command('status'))
            if not reply['ok']:
                raise OSError('device status unavailable')
            if reply['result'].get('session') != self.device_session:
                self.device_session = None
                self._connect()
                self._renew()
                reply = self._exchange(self._command('status'))
            self.device_status = reply['result']
            self.fault = None
            if self.interactions is not None:
                try:
                    for item in self.device_status.get('interactions', []):
                        self.interactions.append(item)
                        confirmation = self._exchange(self._command('confirm_interaction',
                            {'interaction_id': item['interaction_id']}))
                        if not confirmation['ok']:
                            raise OSError('interaction confirmation rejected')
                    self.interaction_fault = None
                except Exception as error:
                    self.interaction_fault = str(error)
                    logging.getLogger(__name__).exception('Interaction delivery failed')
        except (OSError, ValueError) as error:
            self._disconnected(error)
        finally:
            self.lock.release()

    def handle(self, value: object) -> dict:
        rid = value.get('request_id') if isinstance(value, dict) else None
        if not isinstance(rid, str) or len(rid) > 64:
            rid = None
        if not self.lock.acquire(blocking=False):
            return error_response(rid, 'unavailable', 'sender busy; retry same ID shortly')
        try:
            cmd = Command.parse(value)
            if cmd.operation == 'hello':
                return response(rid, {'session': self.session, 'retry_seconds': RETRY_SECONDS,
                    'retry_capacity': RETRY_CAPACITY, 'acknowledgment_available': bool(self.interactions is not None and self.device_status and self.device_status.get('acknowledgment_available'))})
            if cmd.operation == 'status':
                return response(rid, {'host_healthy': True, 'connected': self.device_session is not None,
                    'delivery_fault': self.fault, 'last_device_response': self.last_response,
                    'desired_state': self.desired['state'] if self.desired else 'unknown',
                    'upstream_fresh': self.clock() < self.fresh_until,
                    'device': self.device_status, 'interaction_delivery': (self.interaction_fault or 'ready') if self.interactions else 'unavailable'})
            if cmd.session != self.session:
                raise CommandError('session_changed', 'host restarted; handshake required')
            now = self.clock()
            for key, entry in list(self.cache.items()):
                if now - entry[0] >= RETRY_SECONDS:
                    del self.cache[key]
            if rid in self.cache:
                _, previous, reply = self.cache[rid]
                if previous != cmd.to_dict():
                    raise CommandError('request_conflict', 'request ID reused with different content')
                return deepcopy(reply)
            if len(self.cache) >= RETRY_CAPACITY:
                raise CommandError('retry_capacity', 'retry window full')
            if cmd.operation == 'set_state':
                self.desired = dict(cmd.params)
                self.fresh_until = now + cmd.params['valid_for']
            if self.device_session is None and now < self.reconnect_at:
                reply = error_response(rid, 'unavailable', 'device reconnect backoff')
                reply.update(host_accepted=cmd.operation == 'set_state', device_accepted=False,
                             message_replay=False)
                self.cache[rid] = (now, cmd.to_dict(), deepcopy(reply))
                return reply
            try:
                self._connect()
                # Establish desired state before delivering any transient after reconnect.
                if self.renew_at == 0 and cmd.operation != 'set_state':
                    self._renew()
                forwarded = cmd.to_dict()
                forwarded['session'] = self.device_session
                device_reply = self._exchange(forwarded)
                if not device_reply['ok'] and device_reply['error']['code'] == 'session_changed':
                    raise OSError('device restarted; transient command not replayed')
                if cmd.operation == 'set_state' and device_reply['ok']:
                    self.renew_at = now + min(cmd.params['lease_seconds'], cmd.params['valid_for']) / 3
                if device_reply['ok']:
                    reply = response(rid, {**device_reply['result'], 'host_accepted': True,
                                           'device_accepted': True})
                else:
                    reply = {**device_reply, 'host_accepted': cmd.operation == 'set_state',
                             'device_accepted': False}
            except (OSError, ValueError) as error:
                self._disconnected(error)
                reply = error_response(rid, 'delivery_uncertain', str(error))
                reply.update(host_accepted=cmd.operation == 'set_state', device_accepted=None,
                             message_replay=False)
            self.cache[rid] = (now, cmd.to_dict(), deepcopy(reply))
            return reply
        except CommandError as error:
            return error_response(rid, error.code, str(error))
        finally:
            self.lock.release()

    def close(self) -> None:
        with self.lock:
            self.delivery.close()
