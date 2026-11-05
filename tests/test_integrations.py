"""Producer behavior with fake clocks, HTTP sockets and OBS/Videonode payloads."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pinrig_producers.authority import Authority
from pinrig_producers.obs import OBS, live_rigs, publish
from pinrig_producers.rig import accept_obs, make_rig_handler
from pinrig_producers.videonode import ConsumerSnapshot, events, run as run_video
from pinrig_producers.obs import run as run_obs


class Clock:
    now = 0.

    def __call__(self):
        return self.now


class Client:
    def __init__(self):
        self.calls = []

    def send(self, operation, params, *, request_id=None):
        self.calls.append((operation, params, request_id))
        return {'ok': True, 'result': {'message_id': request_id}}


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.client = Client()
        self.authority = Authority('rig1', self.client, clock=self.clock)

    def test_truth_table_including_missing_sources(self):
        for live, video, state in [
            (True, True, 'on_air'), (True, False, 'on_air'), (True, None, 'on_air'),
            (False, True, 'camera_active'), (False, False, 'camera_inactive'),
            (False, None, 'unknown'), (None, True, 'unknown'), (None, False, 'unknown'),
        ]:
            with self.subTest(live=live, video=video):
                self.authority.observe_obs(live, 8)
                self.authority.observe_video(video)
                self.assertEqual(self.authority.resolution().state, state)
        self.authority.observations.clear()
        self.assertEqual(self.authority.resolution().state, 'unknown')
        self.authority.observe_obs(True, 8)
        self.assertEqual(self.authority.resolution().state, 'on_air')

    def test_expiry_is_independent_and_recovery_is_immediate(self):
        self.authority.observe_obs(False, 8)
        self.authority.observe_video(True)
        self.clock.now = 8
        self.assertEqual(self.authority.resolution().state, 'unknown')
        self.authority.observe_obs(False, 8)
        self.assertEqual(self.authority.resolution().state, 'camera_active')
        self.clock.now = 31
        self.authority.observe_obs(False, 8)
        self.assertEqual(self.authority.resolution().state, 'unknown')
        self.authority.observe_video(False)
        self.assertEqual(self.authority.resolution().state, 'camera_inactive')

    def test_observation_boundary_rejects_wrong_rig_and_invalid_facts(self):
        for value in [None, {}, {'rig': 'rig2', 'live': True, 'valid_for': 8},
                      {'rig': 'rig1', 'live': 'false', 'valid_for': 8},
                      {'rig': 'rig1', 'live': False, 'valid_for': 9},
                      {'rig': 'rig1', 'live': False, 'valid_for': float('nan')},
                      {'rig': 'rig1', 'live': False, 'valid_for': True}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                accept_obs(self.authority, value)
        accept_obs(self.authority, {'rig': 'rig1', 'live': True, 'valid_for': 2})
        self.clock.now = 2
        self.assertEqual(self.authority.resolution().state, 'unknown')

    def test_publishes_short_lived_resolved_state(self):
        self.authority.observe_obs(False, 8)
        self.authority.observe_video(True)
        self.authority.publish()
        operation, params, _ = self.client.calls[-1]
        self.assertEqual((operation, params['state']), ('set_state', 'camera_active'))
        self.assertEqual(params['valid_for'], 3)
        self.assertEqual(params['lease_seconds'], 3)
        self.clock.now = 8
        self.authority.publish()
        self.assertEqual(self.client.calls[-1][1]['state'], 'unknown')

    def test_booth_messages_require_ack_and_clear_is_cancellation(self):
        self.authority.message('Player ready', 'booth-123')
        operation, params, request_id = self.client.calls[-1]
        self.assertEqual(operation, 'show_message')
        self.assertEqual(request_id, 'booth-123')
        self.assertTrue(params['requires_ack'])
        self.assertEqual(params['body'], 'Player ready')
        self.authority.clear('booth-123')
        self.assertEqual(self.client.calls[-1][:2], ('cancel_message', {'message_id': 'booth-123'}))
        for body in ['', 'a' * 241, '\x00']:
            with self.assertRaises(ValueError):
                self.authority.message(body, 'booth-123')
        with self.assertRaises(ValueError):
            self.authority.clear('other-producer')


class FakeOBS:
    def __init__(self, *, auth=False, streaming=True, scene='Rig 1', fail=False):
        self.queue = [{'op': 0, 'd': {'authentication': {'salt': 'salt', 'challenge': 'challenge'}}
                       if auth else {}}]
        self.sent = []
        self.streaming, self.scene, self.fail = streaming, scene, fail

    def recv(self):
        return json.dumps(self.queue.pop(0))

    def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        if value['op'] == 1:
            self.queue.append({'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        else:
            data = value['d']
            response = ({'outputActive': self.streaming} if data['requestType'] == 'GetStreamStatus'
                        else {'currentProgramSceneName': self.scene})
            self.queue.append({'op': 7, 'd': {**data, 'requestStatus': {'result': not self.fail},
                                             'responseData': response}})


class OBSTests(unittest.TestCase):
    def test_scene_mapping_streaming_both_other_and_stopped(self):
        for streaming, scene, expected in [
            (True, 'Rig 1', (True, False)), (True, 'Rig 2', (False, True)),
            (True, 'MEGA PINBALL', (True, True)), (False, 'MEGA PINBALL', (False, False)),
            (True, 'Break', (False, False)), (True, 'rig 1', (False, False)),
        ]:
            with self.subTest(scene=scene, streaming=streaming):
                self.assertEqual(tuple(live_rigs(streaming, scene).values()), expected)
        for streaming, scene in [('false', 'Rig 1'), (False, None), (True, '')]:
            with self.assertRaises(ValueError):
                live_rigs(streaming, scene)

    def test_authenticated_handshake_and_snapshot_use_program_and_stream(self):
        socket = FakeOBS(auth=True, scene='MEGA PINBALL')
        obs = OBS(socket, 'password')
        secret = base64.b64encode(hashlib.sha256(b'passwordsalt').digest())
        expected = base64.b64encode(hashlib.sha256(secret + b'challenge').digest()).decode()
        self.assertEqual(socket.sent[0]['d']['authentication'], expected)
        self.assertEqual(socket.sent[0]['d']['eventSubscriptions'], 0)
        self.assertEqual(obs.snapshot(), {'rig1': True, 'rig2': True})
        self.assertEqual([v['d'].get('requestType') for v in socket.sent[1:]],
                         ['GetStreamStatus', 'GetCurrentProgramScene'])

    def test_obs_failure_never_becomes_negative_evidence(self):
        with self.assertRaises(ValueError):
            OBS(FakeOBS(fail=True), '').snapshot()
        socket = FakeOBS()
        socket.queue = [{'op': 0, 'd': {'authentication': []}}]
        with self.assertRaises(ValueError):
            OBS(socket, '')

    def test_report_aging_and_failed_rig_do_not_block_other_rig(self):
        clock, calls = Clock(), []

        def post(url, value, **kwargs):
            calls.append((url, value))
            clock.now += 2
            if 'one' in url:
                raise OSError('unreachable')

        publish({'rig1': 'http://one', 'rig2': 'http://two'}, {'rig1': True, 'rig2': False},
                sampled_at=0, clock=clock, post=post)
        self.assertEqual([c[1]['rig'] for c in calls], ['rig1', 'rig2'])
        self.assertEqual([c[1]['valid_for'] for c in calls], [8, 6])
        clock.now = 8
        publish({'rig1': 'http://one'}, {'rig1': True}, sampled_at=0, clock=clock, post=post)
        self.assertEqual(len(calls), 2)

    def test_generator_publishes_unknown_on_disconnect_then_queries_after_reconnect(self):
        class Stop:
            count = 0
            def is_set(self): return self.count >= 2
            def wait(self, duration): self.count += 1

        class Socket(FakeOBS):
            closed = False
            def close(self): self.closed = True

        first, second = Socket(fail=True), Socket(scene='Rig 2')
        sockets, reports = iter([first, second]), []
        run_obs({'rig1': 'http://one', 'rig2': 'http://two'}, Stop(),
                connect=lambda *a, **k: next(sockets), clock=Clock(),
                post=lambda url, value, **kwargs: reports.append(value))
        self.assertEqual([r['live'] for r in reports], [None, None, False, True])
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)


class VideonodeTests(unittest.TestCase):
    def event(self, snapshot, stream_id, total):
        snapshot.apply('entity', {'type': 'stream.consumers', 'id': stream_id, 'payload': {'total': total}})

    def test_aggregate_consumers_and_unknown_until_complete(self):
        snapshot = ConsumerSnapshot({'streams': [{'stream_id': 'a'}, {'stream_id': 'b'}]})
        self.assertIsNone(snapshot.active)
        self.event(snapshot, 'a', 0)
        self.assertIsNone(snapshot.active)
        self.event(snapshot, 'b', 1)
        self.assertTrue(snapshot.active)
        self.event(snapshot, 'b', 0)
        self.assertFalse(snapshot.active)
        snapshot.apply('entity', {'type': 'stream.created', 'id': 'c'})
        self.assertIsNone(snapshot.active)
        snapshot.apply('entity', {'type': 'stream.deleted', 'id': 'c'})
        self.assertFalse(snapshot.active)
        self.assertFalse(ConsumerSnapshot({'streams': []}).active)

    def test_malformed_data_does_not_mean_inactive(self):
        for listing in [None, {}, {'streams': [None]}, {'streams': [{'stream_id': 'x'}, {'stream_id': 'x'}]}]:
            with self.assertRaises(ValueError):
                ConsumerSnapshot(listing)
        snapshot = ConsumerSnapshot({'streams': []})
        for total in [None, True, -1, '0']:
            with self.assertRaises(ValueError):
                self.event(snapshot, 'a', total)
        self.assertFalse(snapshot.apply('entity', {'type': 'source.consumers', 'id': 'a'}))

    def test_sse_frames_multiline_heartbeat_eof_and_size_bound(self):
        stream = BytesIO(b':comment\n\nevent: entity\ndata: {"type":"stream.consumers",\ndata: "id":"a","payload":{"total":1}}\n\nevent: heartbeat\ndata: {}\n\n')
        decoder = events(stream)
        self.assertEqual(next(decoder)[1]['payload']['total'], 1)
        self.assertEqual(next(decoder), ('heartbeat', {}))
        with self.assertRaises(OSError):
            next(decoder)
        with self.assertRaises(ValueError):
            next(events(BytesIO(b'data: ' + b'x' * 65536 + b'\n')))

    def test_disconnect_invalidates_evidence_and_reconnect_resets_counts(self):
        class Stop:
            stopped = False
            def is_set(self): return self.stopped
            def wait(self, duration): self.stopped = True

        class Stream(BytesIO):
            pass

        evidence = []
        class Sink:
            def observe_video(self, value): evidence.append(value)

        run_video('http://vn', Sink(), Stop(), get_json=lambda *a, **k: {'streams': [{'stream_id': 'a'}]},
            open_stream=lambda *a, **k: Stream(b'event: entity\ndata: {"type":"stream.consumers","id":"a","payload":{"total":1}}\n\n'))
        self.assertEqual(evidence[0], True)
        self.assertIsNone(evidence[-1])

    def test_planned_resync_does_not_publish_partial_zero_counts_as_unknown(self):
        class Stop:
            stopped = False
            waits = []
            def is_set(self): return self.stopped
            def wait(self, duration):
                self.waits.append(duration)
                self.stopped = len(self.waits) == 2

        evidence = []
        class Sink:
            def observe_video(self, value): evidence.append(value)

        def count(stream_id):
            return ('event: entity\ndata: ' + json.dumps({'type': 'stream.consumers',
                    'id': stream_id, 'payload': {'total': 0}}) + '\n\n').encode()

        heartbeat = b'event: heartbeat\ndata: {}\n\n'
        streams = iter([BytesIO(count('a') + count('b') + heartbeat),
                        BytesIO(heartbeat + count('a') + count('b'))])
        moments = iter([0, 0, 0, 21, 21, 21, 21, 21])
        stop = Stop()
        run_video('http://vn', Sink(), stop, clock=lambda: next(moments),
            get_json=lambda *a, **k: {'streams': [{'stream_id': 'a'}, {'stream_id': 'b'}]},
            open_stream=lambda *a, **k: next(streams))
        # None appears only after the second connection fails, not during resync.
        self.assertEqual(evidence, [False, False, None, None])
        self.assertEqual(stop.waits, [2, 1])


class BoothContractTests(unittest.TestCase):
    def test_booth_survives_duration_tap_and_web_clear_are_distinct(self):
        from display_controller.controller import DisplayController
        from pinrig_protocol.interactions import InteractionStore
        from tests.helpers import Clock as DeviceClock, Display, Pages
        from pinrig_host.delivery import LocalDelivery
        from pinrig_host.service import Host
        from pinrig_producers.client import Client as HTTPClient

        with TemporaryDirectory() as directory:
            clock = DeviceClock()
            controller = DisplayController(display=Display(), pages=Pages(), clock=clock,
                interactions=InteractionStore(Path(directory) / 'device.sqlite3'))
            host = Host(LocalDelivery(controller), clock=clock,
                interactions=InteractionStore(Path(directory) / 'host.sqlite3'))

            class LocalClient(HTTPClient):
                def __init__(self): super().__init__('http://unused')
                def _send(self, operation, params, request_id):
                    command = {'version': 1, 'operation': operation, 'params': params,
                               'request_id': request_id}
                    if self.session: command['session'] = self.session
                    return host.handle(command)

            authority = Authority('rig1', LocalClient(), clock=clock)
            controller.start()
            try:
                authority.observe_obs(False, 8)
                authority.observe_video(True)
                self.assertTrue(authority.publish()['ok'])
                self.assertTrue(authority.message('Tap me', 'booth-tap')['ok'])
                for _ in range(12):
                    clock.advance(1)
                    authority.observe_obs(False, 8)
                    authority.observe_video(True)
                    authority.publish()
                    controller.tick()
                self.assertEqual(controller.status()['visible_message']['message_id'], 'booth-tap')
                controller.touch(False)
                controller.touch(True)
                controller.touch(False)
                host.tick()
                status = authority.status()['host']['result']['device']
                self.assertEqual(status['recent_messages']['booth-tap'], 'acknowledged')
                self.assertTrue(authority.message('Clear me', 'booth-clear')['ok'])
                self.assertEqual(authority.clear('booth-clear')['result']['status'], 'cancelled')
                self.assertEqual([v['message_id'] for v in host.interactions.pending()], ['booth-tap'])
                self.assertTrue(authority.message('Keep me', 'booth-retained')['ok'])
                self.assertTrue(authority.message('Queued', 'booth-queued')['ok'])
                authority.observe_obs(None, 8)
                authority.publish()
                self.assertTrue(authority.message('Unknown', 'booth-unknown')['ok'])
                clock.advance(.5)
                controller.tick()
                # Lease loss also preserves all three messages and permits a tap.
                clock.advance(4)
                controller.tick()
                status = controller.status()
                self.assertEqual(status['displayed_state'], 'unknown')
                self.assertEqual(status['visible_message']['message_id'], 'booth-retained')
                self.assertEqual(status['pending'], ['booth-queued', 'booth-unknown'])
                controller.touch(False)
                controller.touch(True)
                controller.touch(False)
                self.assertEqual(controller.status()['recent_messages']['booth-retained'], 'acknowledged')
                self.assertEqual(authority.clear('booth-queued')['result']['status'], 'cancelled')
                authority.observe_obs(False, 8)
                authority.publish()
                self.assertEqual(controller.status()['visible_message']['message_id'], 'booth-unknown')
            finally:
                host.close()
                controller.close()


class FakeConnection:
    def __init__(self, raw):
        self.input, self.output = BytesIO(raw), BytesIO()
    def makefile(self, *args): return self.input
    def sendall(self, data): self.output.write(data)
    def settimeout(self, timeout): pass


class RigHTTPTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.authority = Authority('rig1', self.client, clock=Clock())

    def request(self, path, value=None, *, token='', headers=None):
        payload = b'' if value is None else json.dumps(value).encode()
        method = 'GET' if value is None else 'POST'
        fields = {'Host': 'rig1:48194', 'Content-Type': 'application/json',
                  'Content-Length': str(len(payload)), **(headers or {})}
        raw = (f'{method} {path} HTTP/1.0\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode() + payload
        socket = FakeConnection(raw)
        make_rig_handler(self.authority, token=token)(socket, ('127.0.0.1', 0), object())
        header, body = socket.output.getvalue().split(b'\r\n\r\n', 1)
        return int(header.split()[1]), body

    def test_booth_page_and_status(self):
        code, body = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn(b'Message to the rig', body)
        code, body = self.request('/api/status')
        self.assertEqual(json.loads(body)['rig'], 'rig1')
        self.assertEqual(code, 200)

    def test_obs_token_routing_body_bounds_and_json_validation(self):
        report = {'rig': 'rig1', 'live': True, 'valid_for': 8}
        self.assertEqual(self.request('/api/obs', report, token='secret')[0], 401)
        self.assertEqual(self.request('/api/obs', report, token='secret',
                                     headers={'Authorization': 'Bearer secret'})[0], 200)
        self.assertEqual(self.authority.resolution().state, 'on_air')
        self.assertEqual(self.request('/api/obs', {**report, 'rig': 'rig2'})[0], 422)
        self.assertEqual(self.request('/api/obs', report, headers={'Content-Length': '9000'})[0], 422)
        self.assertEqual(self.request('/api/obs', report, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/obs', report, headers={'Transfer-Encoding': 'chunked'})[0], 415)
        self.assertEqual(self.request('/api/commands', report)[0], 404)

    def test_booth_send_clear_and_cross_origin_rejection(self):
        code, _ = self.request('/api/messages', {'body': 'Ready', 'request_id': 'booth-abc'})
        self.assertEqual(code, 200)
        self.assertTrue(self.client.calls[-1][1]['requires_ack'])
        self.assertEqual(self.request('/api/clear', {'message_id': 'booth-abc'})[0], 200)
        self.assertEqual(self.client.calls[-1][0], 'cancel_message')
        self.assertEqual(self.request('/api/messages', {'body': ''})[0], 422)
        self.assertEqual(self.request('/api/clear', {'message_id': 'booth-abc'},
                                     headers={'Origin': 'http://elsewhere'})[0], 403)


if __name__ == '__main__':
    unittest.main()
