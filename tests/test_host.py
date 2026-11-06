import unittest
from pinrig_host.service import Host
from pinrig_host.delivery import LocalDelivery, SerialDelivery
from tests.helpers import SerialEndpoint
from tests.helpers import device, command, Clock


class Link(LocalDelivery):
    def __init__(self, controller):
        super().__init__(controller); self.fail = False; self.lost_reply = False; self.sent = []
    def exchange(self, c):
        self.sent.append(c)
        if self.fail: raise OSError('unplugged')
        result = super().exchange(c)
        if self.lost_reply: raise TimeoutError('lost reply')
        return result


class HostTests(unittest.TestCase):
    def setUp(self):
        self.c, self.clock, _ = device()
        self.link = Link(self.c); self.host = Host(self.link, clock=self.clock)
    def send(self, op, rid='r1', **params):
        c = command(op, rid, **params); c['session'] = self.host.session
        return self.host.handle(c)

    def test_latest_state_reconnect_without_replaying_messages(self):
        self.send('set_state', state='on_air', valid_for=100)
        self.send('show_message', 'msg', title='T', body='B')
        self.link.fail = True; self.host.tick()
        self.send('set_state', 'new', state='camera_active', valid_for=100)
        self.link.fail = False; self.clock.advance(10); self.host.tick()
        self.assertEqual(self.c.state, 'camera_active')
        self.assertEqual(len([x for x in self.link.sent if x['operation']=='show_message']), 1)

    def test_upstream_stale_and_restart_unknown(self):
        self.send('set_state', state='on_air', valid_for=2)
        self.clock.advance(3); self.host.tick()
        self.assertEqual(self.c.state, 'unknown')
        restarted = Host(self.link, clock=self.clock); restarted.tick()
        self.assertEqual(self.c.state, 'unknown')

    def test_device_restart_restores_only_current_state(self):
        self.send('set_state', state='on_air')
        new, _, _ = device(); new.session = 'newboot'; self.link.controller = new
        self.host.tick()
        self.assertEqual(new.state, 'on_air')
        self.assertIsNone(new.visible)

    def test_uncertain_message_delivery_cached_without_replay(self):
        self.send('set_state', state='on_air')
        self.link.lost_reply = True
        result = self.send('show_message', 'msg', title='T', body='B')
        self.assertEqual(result['error']['code'], 'delivery_uncertain')
        self.link.lost_reply = False
        self.assertEqual(self.send('show_message', 'msg', title='T', body='B'), result)
        self.assertEqual(len([x for x in self.link.sent if x['operation']=='show_message']), 1)
        self.assertEqual(self.c.visible['id'], 'msg')

    def test_busy_sender_and_conflicting_duplicate(self):
        self.host.lock.acquire()
        try: self.assertEqual(self.send('set_state', state='on_air')['error']['code'], 'unavailable')
        finally: self.host.lock.release()
        self.send('set_state', state='on_air')
        self.assertEqual(self.send('set_state', state='unknown')['error']['code'], 'request_conflict')

    def test_backoff_does_not_spin(self):
        self.link.fail = True
        self.host.tick(); count = len(self.link.sent)
        for _ in range(10): self.host.tick()
        self.assertEqual(len(self.link.sent), count)
        self.clock.advance(1); self.host.tick()
        self.assertGreater(len(self.link.sent), count)


class Stream:
    def __init__(self, endpoint, clock): self.endpoint=endpoint; self.clock=clock; self.buffer=b''; self.closed=False; self.drop=False
    def write(self, data):
        reply = self.endpoint.feed(data)
        if not self.drop: self.buffer += reply
        return len(data)
    def read(self, count):
        self.clock.advance(.1)
        data, self.buffer = self.buffer[:7], self.buffer[7:]
        return data
    def close(self): self.closed=True


class SerialTests(unittest.TestCase):
    def test_fake_serial_and_local_parity(self):
        c, clock, _ = device(); stream = Stream(SerialEndpoint(c), clock)
        delivery = SerialDelivery(lambda: stream, clock=clock, timeout=10)
        result = delivery.exchange(command('set_state', state='on_air'))
        self.assertTrue(result['result']['accepted'])
        delivery.close(); self.assertTrue(stream.closed)

    def test_timeout_closes_owned_stream(self):
        c, clock, _ = device(); stream = Stream(SerialEndpoint(c), clock); stream.drop=True
        delivery = SerialDelivery(lambda: stream, clock=clock)
        with self.assertRaises(TimeoutError): delivery.exchange(command('hello'))
        self.assertTrue(stream.closed)

class BackoffAcceptanceTests(unittest.TestCase):
    def test_requests_during_backoff_do_not_postpone_reconnection(self):
        c, clock, _ = device()
        link = Link(c); link.fail = True
        host = Host(link, clock=clock)
        host.tick()
        deadline = host.reconnect_at
        for i in range(5):
            request = command('set_state', str(i), state='on_air')
            request['session'] = host.session
            reply = host.handle(request)
            self.assertTrue(reply['host_accepted'])
            self.assertFalse(reply['device_accepted'])
        self.assertEqual(host.reconnect_at, deadline)
        link.fail = False; clock.advance(1); host.tick()
        self.assertEqual(c.state, 'on_air')
