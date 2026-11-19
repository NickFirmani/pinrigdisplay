"""Publish OBS WebSocket snapshots to configured rig authorities."""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
import logging
import time
import uuid
from shared.net import request_json
from shared.rig_api import OBS_REPORT_PATH, OBS_VALID_FOR

RIG_1_SCENE = 'Rig 1'
RIG_2_SCENE = 'Rig 2'
BOTH_RIGS_SCENE = 'MEGA PINBALL'
RIG_SCENES = {'rig1': RIG_1_SCENE, 'rig2': RIG_2_SCENE}
LOGGER = logging.getLogger(__name__)


def live_rigs(streaming: bool, scene: str) -> dict[str, bool]:
    """Use the agreed top-level program-scene convention, including both rigs."""
    if type(streaming) is not bool or not isinstance(scene, str) or not scene:
        raise ValueError('OBS must supply streaming status and a program scene')
    return {rig: streaming and scene in (name, BOTH_RIGS_SCENE)
            for rig, name in RIG_SCENES.items()}


class OBS:
    """Small synchronous OBS v5 client; websocket-client is an optional extra."""
    def __init__(self, socket, password: str):
        self.socket = socket
        hello = self.receive(0)
        identify = {'rpcVersion': 1, 'eventSubscriptions': 0}
        if 'authentication' in hello:
            auth = hello['authentication']
            if not isinstance(auth, dict) or not all(isinstance(auth.get(k), str)
                                                    for k in ('salt', 'challenge')):
                raise ValueError('invalid OBS authentication challenge')
            secret = base64.b64encode(hashlib.sha256((password + auth['salt']).encode()).digest()).decode()
            identify['authentication'] = base64.b64encode(
                hashlib.sha256((secret + auth['challenge']).encode()).digest()).decode()
        self.socket.send(json.dumps({'op': 1, 'd': identify}))
        self.receive(2)

    def receive(self, op: int) -> dict:
        raw = self.socket.recv()
        if len(raw) > 65536:
            raise ValueError('OBS response too large')
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('op') != op or not isinstance(value.get('d'), dict):
            raise ValueError('unexpected OBS response')
        return value['d']

    def request(self, name: str) -> dict:
        request_id = uuid.uuid4().hex
        self.socket.send(json.dumps({'op': 6, 'd': {'requestType': name, 'requestId': request_id}}))
        data = self.receive(7)
        status = data.get('requestStatus')
        if (data.get('requestId') != request_id or data.get('requestType') != name
                or not isinstance(status, dict) or status.get('result') is not True
                or not isinstance(data.get('responseData'), dict)):
            raise ValueError(f'OBS {name} failed or returned an invalid response')
        return data['responseData']

    def snapshot(self) -> dict[str, bool]:
        streaming = self.request('GetStreamStatus').get('outputActive')
        scene = self.request('GetCurrentProgramScene').get('currentProgramSceneName')
        self.details = {'streaming': streaming, 'scene': scene}
        return live_rigs(streaming, scene)


def publish(targets: dict[str, str], evidence: dict[str, bool | None], *,
            sampled_at: float, clock=time.monotonic, post=request_json, report=None) -> None:
    """Bound each report to the original snapshot; never queue stale reports."""
    for rig, url in targets.items():
        remaining = OBS_VALID_FOR - (clock() - sampled_at)
        if remaining <= 0:
            if report:
                report(rig, 'observation expired before delivery')
            continue
        try:
            post(url.rstrip('/') + OBS_REPORT_PATH, {'rig': rig, 'live': evidence[rig],
                 'valid_for': remaining})
            if report:
                report(rig, None)
        except (OSError, ValueError) as error:
            if report:
                report(rig, str(error))
            LOGGER.warning('OBS report to %s failed: %s', rig, error)


def run(targets, stop, *, url='ws://127.0.0.1:4455', password='',
        connect=None, clock=time.monotonic, post=request_json, status=None, mappings=None) -> None:
    transport_errors = (OSError, ValueError)
    if connect is None:
        from websocket import WebSocketException, create_connection
        connect = create_connection
        transport_errors += (WebSocketException,)
    socket, obs = None, None
    executor = ThreadPoolExecutor(max_workers=len(targets)) if status else None
    try:
        while not stop.is_set():
            sampled_at = clock()
            try:
                if obs is None:
                    socket = connect(url, timeout=2, subprotocols=['obswebsocket.json'])
                    obs = OBS(socket, password)
                evidence = obs.snapshot()
                if mappings is not None:
                    evidence = {rig: obs.details['streaming'] and obs.details['scene'] in mappings[rig] for rig in targets}
                if status:
                    status.observed({**obs.details, 'connected': True, 'error': None,
                        'scene_recognized': obs.details['scene'] in {scene for scenes in mappings.values() for scene in scenes} if mappings is not None else obs.details['scene'] in (*RIG_SCENES.values(), BOTH_RIGS_SCENE)})
            except transport_errors as error:
                LOGGER.warning('OBS unavailable: %s', error)
                if socket is not None:
                    socket.close()
                socket, obs = None, None
                evidence = {rig: None for rig in targets}
                if status:
                    status.observed({'connected': False, 'error': str(error), 'scene': None, 'streaming': None})
            if executor:
                pending = [executor.submit(publish, {rig: target}, evidence,
                    sampled_at=sampled_at, clock=clock, post=post, report=status.delivered)
                    for rig, target in targets.items()]
                for future in pending:
                    future.result()
            else:
                publish(targets, evidence, sampled_at=sampled_at, clock=clock, post=post)
            stop.wait(1)
    finally:
        if executor:
            executor.shutdown(wait=True)
        if socket is not None:
            socket.close()
