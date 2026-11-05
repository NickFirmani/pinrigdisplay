"""Combined rig lifecycle and local delivery without sockets, hardware or sleeps."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pinrig_host.client import LocalClient
from pinrig_host.delivery import LocalDelivery
from pinrig_host.service import Host
from pinrig_protocol.interactions import InteractionStore
from pinrig_producers.authority import Authority
from pinrig_producers.rig import run_delivery, run_service
from tests.helpers import device


class LocalClientTests(unittest.TestCase):
    def test_local_commands_retain_validation_deduplication_and_uncertain_delivery(self):
        controller, clock, _ = device()

        class LostReply(LocalDelivery):
            lost = False
            messages = 0
            def exchange(self, value):
                reply = super().exchange(value)
                if value['operation'] == 'show_message':
                    self.messages += 1
                    if self.lost:
                        raise OSError('lost reply')
                return reply

        link = LostReply(controller)
        host = Host(link, clock=clock)
        client = LocalClient(host)
        self.addCleanup(host.close)
        self.addCleanup(controller.close)
        self.assertTrue(client.send('set_state', {'state': 'camera_active'})['ok'])
        self.assertEqual(client.send('set_state', {'state': 'invalid'})['error']['code'], 'invalid_request')
        link.lost = True
        message = {'title': 'BOOTH', 'body': 'Ready'}
        first = client.send('show_message', message, request_id='booth-once')
        self.assertEqual(first['error']['code'], 'delivery_uncertain')
        self.assertEqual(client.send('show_message', message, request_id='booth-once'), first)
        self.assertEqual(link.messages, 1)
        self.assertEqual(controller.status()['visible_message']['message_id'], 'booth-once')


class RuntimeTests(unittest.TestCase):
    def test_delivery_loop_renews_state_and_durably_confirms_taps(self):
        controller, clock, _ = device()
        self.addCleanup(controller.close)
        with TemporaryDirectory() as directory:
            controller.interactions = InteractionStore(Path(directory) / 'device.sqlite3')
            controller.touch_available = True
            store = InteractionStore(Path(directory) / 'host.sqlite3')
            host = Host(LocalDelivery(controller), clock=clock, interactions=store)
            self.addCleanup(host.close)
            authority = Authority('rig1', LocalClient(host), clock=clock)
            authority.observe_obs(False, 8)
            authority.observe_video(True)
            authority.publish()
            self.assertTrue(authority.message('Ready', 'booth-tap')['ok'])
            clock.advance(.5)
            controller.tick()
            controller.touch(False); controller.touch(True); controller.touch(False)

            class Stop:
                waits = 0
                def is_set(self): return self.waits == 9
                def wait(self, duration):
                    self.waits += 1
                    clock.advance(duration)

            run_delivery(authority, host, Stop(), clock=clock)
            self.assertTrue(host.handle({'version': 1, 'request_id': 'status',
                                         'operation': 'status'})['result']['upstream_fresh'])
            self.assertEqual([item['message_id'] for item in store.pending()], ['booth-tap'])
            self.assertEqual(controller.interactions.pending(), [])

    def test_failed_publication_does_not_stop_usb_polling(self):
        calls = []
        class Authority:
            def publish(self):
                raise OSError('unavailable')
        class Host:
            def tick(self): calls.append('tick')
        class Stop:
            done = False
            def is_set(self): return self.done
            def wait(self, duration): self.done = True
        with self.assertLogs('pinrig_producers.rig', level='WARNING'):
            run_delivery(Authority(), Host(), Stop(), clock=lambda: 0)
        self.assertEqual(calls, ['tick'])

    def test_listener_failure_closes_owned_usb_host(self):
        closed = []
        class Host:
            def close(self): closed.append(True)
        class Stop:
            def set(self): pass
        def fail(*args): raise OSError('address in use')
        with self.assertRaises(OSError):
            run_service(None, Host(), Stop(), bind='localhost', port=48194,
                        videonode_url='http://unused', server_factory=fail)
        self.assertEqual(closed, [True])

    def test_shutdown_drains_workers_before_closing_usb(self):
        calls = []
        class Server:
            daemon_threads = True
            def __init__(self, *args): pass
            def serve_forever(self): pass
            def shutdown(self): calls.append('shutdown')
            def server_close(self):
                calls.append(('drain', not self.daemon_threads))
        class Worker:
            ident = None
            def __init__(self, **kwargs): pass
            def start(self): self.ident = 1
            def join(self): calls.append('join')
        class Host:
            def close(self): calls.append('close_usb')
        class Stop:
            def is_set(self): return True
            def set(self): calls.append('stop')
        class Authority:
            rig = 'rig1'
        run_service(Authority(), Host(), Stop(), bind='localhost', port=48194,
                    videonode_url='http://unused', server_factory=Server, thread_factory=Worker)
        self.assertEqual(calls, ['stop', 'shutdown', ('drain', True), 'join', 'join', 'close_usb'])
