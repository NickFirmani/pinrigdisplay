"""Touch gestures and durable receipt tests without hardware or real delays."""
from pathlib import Path
import tempfile
import unittest
from pinrig_protocol.interactions import InteractionStore
from pinrig_host.service import Host
from pinrig_host.delivery import LocalDelivery
from display_controller.touch import XPT2046
from tests.helpers import device, command


class TouchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c, self.clock, _ = device()
        self.store = InteractionStore(Path(self.temp.name)/'outbox.db', capacity=2)
        self.c.interactions = self.store
        self.c.touch_available = True
        self.c.handle(command('set_state', state='on_air', lease_seconds=60, valid_for=60))
        self.clock.advance(.5); self.c.tick()

    def message(self, mid='booth', ack=True):
        reply = self.c.handle(command('show_message', mid, title='BOOTH', body='Please check camera', requires_ack=ack))
        self.assertTrue(reply['ok'], reply)
        self.clock.advance(.5); self.c.tick()

    def tap(self):
        self.c.touch(False); self.c.touch(True); self.c.touch(False)

    def test_ack_persists_before_dismissal_and_replays_after_restart(self):
        self.message(); self.clock.advance(20); self.c.tick()
        self.assertIsNotNone(self.c.visible)
        self.tap()
        self.assertIsNone(self.c.visible)
        records = InteractionStore(self.store.path).pending()
        self.assertEqual(records[0]['message_id'], 'booth')
        self.assertEqual(records[0]['kind'], 'acknowledged')
        reply = self.c.handle(command('confirm_interaction', 'confirm', interaction_id=records[0]['interaction_id']))
        self.assertTrue(reply['ok']); self.assertEqual(self.store.pending(), [])

    def test_initial_held_press_is_ignored(self):
        self.message(); self.c.touch(True); self.c.touch(False)
        self.assertIsNotNone(self.c.visible)
        self.tap(); self.assertIsNone(self.c.visible)

    def test_replacement_and_layout_invalidate_gesture(self):
        self.message(); self.c.touch(False); self.c.touch(True)
        self.c.handle(command('cancel_message', 'cancel', message_id='booth'))
        self.message('replacement'); self.c.touch(False)
        self.assertEqual(self.c.visible.id, 'replacement')
        self.assertEqual(self.store.pending(), [])

    def test_opening_press_is_not_acknowledgment(self):
        self.c.handle(command('show_message', 'a', title='T', body='B', requires_ack=True))
        self.c.touch(False); self.c.touch(True)
        self.clock.advance(.5); self.c.tick(); self.c.touch(False)
        self.assertIsNotNone(self.c.visible)

    def test_full_outbox_retains_card_and_reports_fault(self):
        for mid in ('a','b'):
            self.message(mid); self.tap()
        self.message('c')
        with self.assertLogs('display_controller.controller', level='ERROR'): self.tap()
        self.assertEqual(self.c.visible.id, 'c')
        self.assertIn('full', self.c.status()['touch_fault'])

    def test_write_failure_retains_card(self):
        self.message()
        def fail(_): raise OSError('disk failed')
        self.store.append = fail
        with self.assertLogs('display_controller.controller', level='ERROR'): self.tap()
        self.assertEqual(self.c.visible.id, 'booth')
        self.assertEqual(self.store.pending(), [])

    def test_timed_dismissal_is_distinct_from_ack(self):
        self.message(ack=False); self.tap()
        self.assertEqual(self.store.pending()[0]['kind'], 'dismissed')

    def test_input_failure_keeps_sign_operational(self):
        self.message(); self.c.touch_failed('reader disconnected')
        self.assertFalse(self.c.status()['acknowledgment_available'])
        self.assertTrue(self.c.status()['healthy'])
        self.assertIsNotNone(self.c.visible)

    def test_host_stores_before_confirming_and_deduplicates(self):
        self.message(); self.tap()
        record = self.store.pending()[0]
        host_store = InteractionStore(Path(self.temp.name)/'host.db')
        host = Host(LocalDelivery(self.c), clock=self.clock, interactions=host_store)
        host.tick()
        self.assertEqual(host_store.pending(), [record]); self.assertEqual(self.store.pending(), [])
        self.store.append(record); host.tick()
        self.assertEqual(host_store.pending(), [record]); self.assertEqual(self.store.pending(), [])

    def test_host_storage_failure_does_not_confirm(self):
        self.message(); self.tap()
        host_store = InteractionStore(Path(self.temp.name)/'host.db', capacity=0)
        host = Host(LocalDelivery(self.c), clock=self.clock, interactions=host_store)
        with self.assertLogs('pinrig_host.service', level='ERROR'): host.tick()
        self.assertEqual(len(self.store.pending()), 1)
        self.assertIn('full', host.interaction_fault)

    def test_unreadable_outbox_reports_touch_fault_without_losing_sign(self):
        self.message()
        def fail(): raise OSError('database unreadable')
        self.store.pending = fail
        with self.assertLogs('display_controller.controller', level='ERROR'):
            status = self.c.status()
        self.assertTrue(status['healthy'])
        self.assertFalse(status['acknowledgment_available'])
        self.assertIn('unreadable', status['touch_fault'])
        self.assertIsNotNone(self.c.visible)


class XPTTests(unittest.TestCase):
    def test_pressure_decode_and_resource_cleanup(self):
        class SPI:
            def open(self, bus, device): self.device = (bus, device)
            def xfer2(self, data):
                value = 600 if data[0] == 0xB0 else 2800
                return [0, (value << 3) >> 8, (value << 3) & 255]
            def close(self): self.closed = True
        spi = SPI(); reader = XPT2046(spi)
        self.assertTrue(reader.pressed())
        self.assertEqual(spi.device, (0, 1)); self.assertEqual(spi.max_speed_hz, 100000)
        reader.close(); self.assertTrue(spi.closed)
