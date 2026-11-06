"""Rig smoke workflow with injected transport and clock, without hardware."""
import unittest
from tools.usb_smoke import check_rig


class RigAPI:
    def __init__(self):
        self.state = 'unknown'
        self.card = None
        self.calls = []
        self.fail_message = False
        self.connected = True

    def __call__(self, url, value=None, **kwargs):
        path = url.split('/api/')[1]
        self.calls.append((path, value, kwargs))
        if path == 'status':
            return {'rig': 'rig1', 'host': {'ok': True, 'result': {
                'connected': self.connected, 'device': {'healthy': True,
                'displayed_state': self.state, 'visible_message': self.card, 'pending': []}}}}
        if path == 'obs':
            self.state = 'on_air' if value['live'] else 'unknown'
        elif path == 'messages':
            self.card = {'message_id': value['request_id']}
            if self.fail_message:
                raise OSError('reply lost')
        elif path == 'clear':
            self.card = None
        return {'ok': True}


class SmokeTests(unittest.TestCase):
    def test_workflow_uses_rig_routes_and_token(self):
        api = RigAPI()
        check_rig('http://rig:48194/', 'rig1', token='secret', request=api)
        self.assertEqual([x[0] for x in api.calls if x[0] != 'status'],
                         ['obs', 'messages', 'obs', 'clear', 'obs'])
        self.assertTrue(all(x[2]['headers']['Authorization'] == 'Bearer secret' for x in api.calls))
        self.assertIsNone(api.card)
        self.assertEqual(api.state, 'unknown')

    def test_lost_message_reply_still_cleans_up(self):
        api = RigAPI()
        api.fail_message = True
        with self.assertRaisesRegex(OSError, 'reply lost'):
            check_rig('http://rig', 'rig1', request=api)
        self.assertIsNone(api.card)
        self.assertEqual(api.state, 'unknown')

    def test_wrong_rig_or_disconnected_device_fails_before_mutations(self):
        for rig, connected in [('rig2', True), ('rig1', False)]:
            api = RigAPI()
            api.connected = connected
            with self.subTest(rig=rig, connected=connected), self.assertRaises(RuntimeError):
                check_rig('http://rig', rig, request=api)
            self.assertEqual([x[0] for x in api.calls], ['status'])

    def test_wait_is_bounded_with_injected_clock(self):
        api = RigAPI()
        now = [0.]
        def request(url, value=None, **kwargs):
            result = api(url, value, **kwargs)
            api.state = 'unknown'
            return result
        def delay(seconds):
            now[0] += seconds
        with self.assertRaisesRegex(RuntimeError, 'expected state'):
            check_rig('http://rig', 'rig1', request=request,
                      clock=lambda: now[0], delay=delay, timeout=.4)
        self.assertIsNone(api.card)
