"""One rig's source evidence and serialized display command writer."""
import threading
import time
from pinrig_protocol.commands import Command, identifier
from .policy import Observation, resolve

SOURCE_MAX_AGE = 30.
OBS_VALID_FOR = 8.


class Authority:
    def __init__(self, rig: str, client, *, clock=time.monotonic):
        self.rig = identifier(rig, 'rig')
        self.client = client
        self.clock = clock
        self.lock = threading.Lock()
        self.sender_lock = threading.Lock()
        self.observations = {}
        self.obs_until = 0.
        self.last_delivery = None

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

    def message(self, body: str, request_id: str) -> dict:
        identifier(request_id, 'request_id')
        if not request_id.startswith('booth-'):
            raise ValueError('booth request IDs must start with booth-')
        params = Command.parse({'version': 1, 'request_id': request_id, 'session': 'validate',
            'operation': 'show_message', 'params': {'title': 'BOOTH', 'body': body,
                'priority': 8, 'requires_ack': True}}).params
        return self.send('show_message', params, request_id=request_id)

    def clear(self, message_id: str) -> dict:
        identifier(message_id, 'message_id')
        if not message_id.startswith('booth-'):
            raise ValueError('only booth messages can be cleared here')
        return self.send('cancel_message', {'message_id': message_id})

    def status(self) -> dict:
        resolution = self.resolution()
        return {'rig': self.rig, 'state': resolution.state, 'reason': resolution.reason,
                'host': self.send('status', {}), 'state_delivery': self.last_delivery}
