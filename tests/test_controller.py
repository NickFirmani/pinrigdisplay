import unittest
from tests.helpers import device, command


class ControllerTests(unittest.TestCase):
    def setUp(self): self.c, self.clock, self.display = device()
    def send(self, op, rid='r1', **params): return self.c.handle(command(op, rid, **params))
    def state(self): return self.send('set_state', state='on_air', lease_seconds=60, valid_for=300)
    def message(self, rid, **params):
        return self.send('show_message', rid, title='Title', body='Body', **params)

    def test_startup_and_lease_loss(self):
        self.assertEqual(self.c.status()['displayed_state'], 'unknown')
        self.assertEqual(self.c.height, 320)
        self.state(); self.message('msg', duration=120); self.message('pending')
        self.clock.advance(.5); self.c.tick()
        self.assertEqual(self.c.height, 188)
        self.clock.advance(60); self.c.tick()
        s = self.c.status()
        self.assertEqual(s['displayed_state'], 'unknown')
        self.assertEqual(s['visible_message']['message_id'], 'msg')
        self.assertEqual(s['pending'], ['pending'])
        self.assertEqual(s['recent_messages'], {})
        self.assertEqual(self.c.height, 188)
        self.assertEqual(s['diagnostic'], 'Host command lease expired')

    def test_unknown_and_recovery_preserve_message_and_transition(self):
        self.state(); self.message('msg')
        self.clock.advance(.25); self.c.tick()
        height = self.c.height
        self.send('set_state', 'unknown-state', state='unknown', diagnostic='OBS unavailable')
        self.assertEqual(self.c.height, height)
        self.assertEqual(self.c.visible.id, 'msg')
        self.assertEqual(self.c.status()['diagnostic'], 'OBS unavailable')
        self.assertEqual(self.c.frame_interval(8), 1/30)
        self.clock.advance(.25); self.c.tick()
        self.assertEqual(self.c.height, 188)
        self.send('set_state', 'unknown-renewal', state='unknown')
        self.send('set_state', 'recovered', state='camera_active')
        self.assertEqual(self.c.visible.id, 'msg')
        self.assertEqual(self.c.height, 188)
        self.assertEqual(self.c.frame_interval(8), 1/8)

    def test_unknown_accepts_messages_and_touch_capability_is_still_required(self):
        self.assertTrue(self.message('a')['ok'])
        self.state()
        self.assertEqual(self.message('b', requires_ack=True)['error']['code'], 'ack_unavailable')
        self.assertEqual(self.send('confirm_interaction', 'c', interaction_id='x')['error']['code'], 'ack_unavailable')

    def test_timed_message_still_expires_while_unknown(self):
        self.assertTrue(self.message('timed', duration=1)['ok'])
        self.clock.advance(.5); self.c.tick()
        self.clock.advance(1); self.c.tick()
        self.assertEqual(self.c.status()['recent_messages']['timed'], 'expired')
        self.clock.advance(.5); self.c.tick()
        self.assertEqual(self.c.height, 320)

    def test_queue_capacity_priority_and_fifo(self):
        self.state()
        self.message('a', priority=5)
        for rid, priority in [('b', 1), ('c', 3), ('d', 3)]: self.message(rid, priority=priority)
        self.assertEqual(self.message('e')['error']['code'], 'queue_full')
        self.send('cancel_message', 'cancel', message_id='a')
        self.assertEqual(self.c.visible.id, 'c')
        self.send('cancel_message', 'cancel2', message_id='c')
        self.assertEqual(self.c.visible.id, 'd')
        self.message('f', priority=9)
        self.assertEqual(self.c.status()['recent_messages']['d'], 'dropped')
        self.assertEqual(self.c.visible.id, 'f')

    def test_expiry_begins_after_opening_success(self):
        self.state(); self.clock.advance(.5); self.c.tick()
        self.message('a', duration=2)
        self.clock.advance(.25); self.c.tick()
        self.assertIsNone(self.c.visible.expires)
        self.clock.advance(.25); self.c.tick()
        self.assertEqual(self.c.visible.expires, 3.)
        self.clock.advance(1.99); self.c.tick()
        self.assertIsNotNone(self.c.visible)
        self.clock.advance(.01); self.c.tick()
        self.assertIsNone(self.c.visible)
        self.assertEqual(self.c.status()['recent_messages']['a'], 'expired')

    def test_duplicate_does_not_extend_message_or_lease(self):
        self.state(); first = self.message('a', duration=1)
        self.clock.advance(.5); self.c.tick()
        expiry = self.c.visible.expires
        self.assertEqual(first, self.message('a', duration=1))
        self.assertEqual(expiry, self.c.visible.expires)
        self.clock.advance(60); self.state(); self.c.tick()
        self.assertEqual(self.c.requested, 'unknown')

    def test_conflict_session_and_bounded_retry_window(self):
        self.state()
        self.assertEqual(self.send('set_state', state='camera_active')['error']['code'], 'request_conflict')
        wrong = command('show_message', title='T', body='B'); wrong['session'] = 'old'
        self.assertEqual(self.c.handle(wrong)['error']['code'], 'session_changed')
        from unittest.mock import patch
        with patch('display_controller.controller.RETRY_CAPACITY', 1):
            self.assertEqual(self.message('a')['error']['code'], 'retry_capacity')
        self.clock.advance(121)
        self.assertTrue(self.send('set_state', state='camera_active')['ok'])

    def test_cancel_pending_is_not_ack(self):
        self.state(); self.message('a'); self.message('b')
        result = self.send('cancel_message', 'cancel', message_id='b')
        self.assertEqual(result['result']['status'], 'cancelled')
        self.assertEqual(self.c.status()['interactions'], [])

    def test_transition_retargets_current_geometry_and_state_changes_immediately(self):
        self.state(); self.clock.advance(.25); self.c.tick()
        height = self.c.height
        self.message('a')
        self.assertEqual(self.c.height, height)
        self.send('set_state', 'new', state='camera_active')
        self.assertEqual(self.c.displayed, 'camera_active')
        self.assertEqual(self.c.visible.id, 'a')

    def test_render_failure_separate_from_acceptance_and_recovers(self):
        self.display.fail = True
        with self.assertLogs('display_controller.controller', level='ERROR'):
            result = self.state()
        self.assertTrue(result['result']['accepted'])
        self.assertFalse(result['result']['display_success'])
        self.assertEqual(self.c.displayed, 'unknown')
        self.display.fail = False; self.c.tick()
        self.assertTrue(self.c.status()['healthy'])
        self.assertEqual(self.c.displayed, 'on_air')

    def test_close_is_idempotent_and_commands_rejected(self):
        self.c.close(); self.c.close()
        self.assertEqual(self.display.closed, 1)
        self.assertEqual(self.state()['error']['code'], 'unavailable')

    def test_duplicate_reply_cannot_mutate_cached_result(self):
        result = self.state(); result['result']['accepted'] = False
        self.assertTrue(self.state()['result']['accepted'])

    def test_failed_opening_does_not_start_message_timer(self):
        self.state(); self.clock.advance(.5); self.c.tick()
        self.display.fail = True
        # Force an actual write even with the simplified test renderer.
        self.c.last_image = None
        with self.assertLogs('display_controller.controller', level='ERROR'):
            self.message('a', duration=2)
            self.clock.advance(3); self.c.tick()
        self.assertIsNone(self.c.visible.expires)
        self.display.fail = False; self.c.tick()
        self.assertEqual(self.c.visible.expires, 5.5)

    def test_initialize_failure_releases_display(self):
        def fail(): raise OSError('init failed')
        self.display.initialize = fail
        with self.assertRaises(OSError): self.c.start()
        self.assertEqual(self.display.closed, 1)

    def test_layout_uses_fast_cadence_then_returns_to_ambient_rate(self):
        self.state()
        self.assertEqual(self.c.frame_interval(8), 1/8)
        self.clock.advance(.5); self.c.tick()
        self.assertEqual(self.c.frame_interval(8), 1/8)
        self.message('a')
        self.assertEqual(self.c.frame_interval(8), 1/30)

    def test_pulse_freezes_at_current_phase_through_open_and_close(self):
        from tests.helpers import Pages
        phases = []
        class RecordingPages(Pages):
            def compose(self, state, message, diagnostic, height, seconds):
                phases.append(seconds)
                return super().compose(state, message, diagnostic, height, seconds)
        self.c.pages = RecordingPages()
        self.state(); self.clock.advance(.5); self.c.tick()
        self.clock.advance(1.25); self.c.tick()
        before = phases[-1]
        self.assertGreater(before, 0)
        self.message('a', duration=30)
        for _ in range(5):
            self.clock.advance(.1); self.c.tick()
            self.assertAlmostEqual(phases[-1], before)
        self.clock.advance(.1); self.c.tick()
        self.assertAlmostEqual(phases[-1], before)
        before = phases[-1]
        self.send('cancel_message', 'cancel', message_id='a')
        for _ in range(5):
            self.clock.advance(.1); self.c.tick()
            self.assertAlmostEqual(phases[-1], before)
        self.clock.advance(.1); self.c.tick()
        self.assertAlmostEqual(phases[-1], before + .1)

    def test_interrupted_layout_does_not_restart_pulse(self):
        from tests.helpers import Pages
        phases = []
        class RecordingPages(Pages):
            def compose(self, state, message, diagnostic, height, seconds):
                phases.append(seconds)
                return super().compose(state, message, diagnostic, height, seconds)
        self.c.pages = RecordingPages()
        self.state(); self.clock.advance(.5); self.c.tick()
        self.clock.advance(1); self.c.tick()
        before = phases[-1]
        self.message('a')
        self.clock.advance(.2); self.c.tick()
        self.send('cancel_message', 'cancel', message_id='a')
        self.clock.advance(.5); self.c.tick()
        self.assertAlmostEqual(phases[-1], before)
        self.clock.advance(.1); self.c.tick()
        self.assertAlmostEqual(phases[-1], before + .1)
