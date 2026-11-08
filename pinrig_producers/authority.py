"""One rig's source evidence and serialized display command writer."""
from .identity import software_identity
import threading
import time
from pinrig_protocol.commands import Command, identifier
from .policy import Observation, resolve

SOURCE_MAX_AGE = 30.
OBS_VALID_FOR = 8.


class Authority:
    def __init__(self, rig: str, client, *, clock=time.monotonic):
        self.software = software_identity()
        self.rig = identifier(rig, 'rig')
        self.client = client
        self.clock = clock
        self.lock = threading.Lock()
        self.sender_lock = threading.Lock()
        self.observations = {}
        self.obs_until = 0.
        self.last_delivery = None
        self.message_details = {}

    def observe_obs(self, live: bool | None, valid_for: float) -> None:
        with self.lock:
            now = self.clock()
            self.observations['obs'] = Observation('obs', self.rig, now, live, False)
            self.obs_until = now + valid_for

    def observe_video(self, active: bool | None) -> None:
        with self.lock:
            self.observations['videonode'] = Observation(
                'videonode', self.rig, self.clock(), False, active)

    def resolution(self):
        with self.lock:
            now = self.clock()
            observations = [o for source, o in self.observations.items()
                            if source != 'obs' or now < self.obs_until]
            return resolve(observations, rig=self.rig, required_sources={'obs', 'videonode'},
                           now=now, max_age=SOURCE_MAX_AGE)

    def send(self, operation: str, params: dict, *, request_id=None) -> dict:
        with self.sender_lock:
            return self.client.send(operation, params, request_id=request_id)

    def publish(self) -> dict:
        # Compute after acquiring the sender: never publish evidence aged in a queue.
        with self.sender_lock:
            resolution = self.resolution()
            reply = self.client.send('set_state', {
                'state': resolution.state, 'diagnostic': resolution.reason,
                'lease_seconds': 3, 'valid_for': 3,
            })
            self.last_delivery = reply
            return reply

    def message(self, body: str, request_id: str, **options) -> dict:
        """Send protocol options; body-only calls retain the booth defaults."""
        identifier(request_id, 'request_id')
        params = ({'title': 'BOOTH', 'priority': 8, 'requires_ack': True}
                  if not options else {})
        params.update(options)
        params['body'] = body
        params = Command.parse({'version': 1, 'request_id': request_id, 'session': 'validate',
            'operation': 'show_message', 'params': params}).params
        with self.sender_lock:
            reply = self.client.send('show_message', params, request_id=request_id)
            with self.lock:
                if reply.get('ok') and request_id not in self.message_details:
                    self.message_details[request_id] = dict(params)
                    if len(self.message_details) > 64:
                        del self.message_details[next(iter(self.message_details))]
            return reply

    def clear(self, message_id: str) -> dict:
        """Cancel a message without recording acknowledgment."""
        identifier(message_id, 'message_id')
        return self.send('cancel_message', {'message_id': message_id})

    def status(self) -> dict:
        resolution = self.resolution()
        host = self.client.send('status', {})
        with self.lock:
            details = dict(self.message_details)
            now = self.clock()
            ages = {name: max(0., now - item.observed_at) for name, item in self.observations.items()}
            sources = {name: {'age': ages[name], 'live': item.live, 'active': item.local_use,
                'fresh': now < self.obs_until if name == 'obs' else ages[name] <= SOURCE_MAX_AGE}
                for name, item in self.observations.items()}
        return {'status_schema': 1, **self.software, 'source_ages': ages, 'sources': sources, 'message_details': details, 'rig': self.rig, 'state': resolution.state, 'reason': resolution.reason,
                'host': host, 'state_delivery': self.last_delivery}
