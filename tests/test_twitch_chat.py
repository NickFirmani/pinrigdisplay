"""Deterministic Twitch grouping and delivery with fake clocks and transports."""
from concurrent.futures import Future
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest

from stream.chat import Chat
from stream.twitch import EVENTSUB, LiveState, Twitch, TwitchError
from tests.helpers import Clock


RIGS = [{'id': 'one'}, {'id': 'two'}]


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sent = []
        self.chat = Chat(RIGS, clock=self.clock, post=self.post)
        self.chat.channel(True, True)
        self.ready()

    def ready(self):
        for rig in RIGS:
            self.chat.report(rig['id'], {'healthy': True})

    def post(self, rig, path, payload):
        self.sent.append((rig['id'], path, payload))
        return {'ok': True, 'result': {'message_id': payload.get('request_id')}}

    def test_deduplicates_ids_and_groups_by_speaker_with_shared_card_id(self):
        self.chat.receive('a', 'user', 'Alice', 'Nice')
        self.chat.receive('a', 'user', 'Alice', 'Nice')
        self.chat.receive('b', 'user', 'Alice', 'Nice')
        self.chat.receive('c', 'other', 'Bob', 'Hello')
        for rig in RIGS:
            self.chat.step(rig)
        first, second = [call[2] for call in self.sent]
        self.assertEqual(first, second)
        self.assertEqual((first['title'], first['body']), ('Alice', 'Nice\nNice'))

    def test_flushes_on_overflow_and_caps_individual_messages(self):
        self.chat.receive('a', 'user', 'N' * 41, 'a' * 245)
        self.chat.receive('b', 'user', 'N' * 41, 'b')
        self.chat.step(RIGS[0])
        card = self.sent[0][2]
        self.assertEqual(card['title'], 'N' * 37 + '...')
        self.assertEqual(card['body'], 'a' * 237 + '...')

    def test_group_timeout_starts_with_first_message(self):
        self.chat.receive('a', 'user', 'Alice', 'First')
        self.clock.advance(2)
        self.chat.receive('b', 'user', 'Alice', 'Second')
        self.chat.step(RIGS[0])
        self.assertFalse(self.sent)
        self.clock.advance(1)
        self.chat.step(RIGS[0])
        self.assertEqual(self.sent[0][2]['body'], 'First\nSecond')

    def test_only_newest_waits_and_expired_cards_are_discarded(self):
        for user in ('a', 'b', 'c'):
            self.chat.receive(user, user, user, user)
        self.chat.step(RIGS[0])
        self.assertEqual(self.sent[0][2]['body'], 'b')
        self.clock.advance(15)
        self.ready()
        self.chat.step(RIGS[1])
        self.assertEqual(len(self.sent), 1)

    def test_newly_eligible_rig_only_receives_new_messages(self):
        self.chat.report('two', {'healthy': False})
        self.chat.receive('a', 'user', 'Alice', 'Before')
        self.ready()
        self.chat.receive('b', 'user', 'Alice', 'After')
        self.chat.step(RIGS[0])
        self.assertEqual(self.sent[0][2]['body'], 'Before')
        self.clock.advance(3)
        self.chat.step(RIGS[1])
        self.assertEqual(self.sent[1][2]['body'], 'After')

    def test_connection_loss_cancels_visible_and_discards_waiting(self):
        for event in ('a', 'b', 'c', 'd'):
            self.chat.receive(event, 'user', 'Alice', event)
        self.chat.step(RIGS[0])
        shown = self.sent[0][2]['request_id']
        self.chat.channel(True, None)
        self.chat.channel(True, True)
        self.chat.receive('d', 'user', 'Alice', 'duplicate')
        self.clock.advance(3)
        for rig in RIGS:
            self.chat.step(rig)
        self.assertEqual(self.sent[1:], [('one', '/api/chat/cancel', {'message_id': shown})])

    def test_slow_rig_never_blocks_another_and_mute_cancels_inflight_card(self):
        entered, release = Event(), Event()

        def post(rig, path, payload):
            if rig['id'] == 'one' and path == '/api/chat':
                entered.set()
                release.wait()
                raise OSError('lost response')
            return self.post(rig, path, payload)

        self.chat.post = post
        for event in ('a', 'b', 'c'):
            self.chat.receive(event, 'user', 'Alice', event)
        worker = Thread(target=self.chat.step, args=(RIGS[0],))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.chat.step(RIGS[1])
            self.assertEqual(self.sent[0][0], 'two')
            self.chat.enable('one', False)
        finally:
            release.set()
            worker.join()
        self.chat.step(RIGS[0])
        self.assertEqual(self.sent[1], ('one', '/api/chat/cancel',
                                       {'message_id': self.sent[0][2]['request_id']}))

    def test_test_card_bypasses_live_but_respects_booth_and_mute(self):
        self.chat.channel(True, False)
        self.chat.test('one')
        self.chat.step(RIGS[0])
        self.assertEqual(self.sent[0][2]['title'], 'Twitch chat')
        self.chat.report('one', {'healthy': True, 'booth': True})
        with self.assertRaises(ValueError):
            self.chat.test('one')
        self.chat.enable('two', False)
        with self.assertRaises(ValueError):
            self.chat.test('two')


class SessionTests(unittest.TestCase):
    def test_preserves_newer_event_on_reconciliation_and_ignores_older_delivery(self):
        state = LiveState()
        state.event(False, '2026-11-19T00:00:02.000000000Z')
        state.reconcile(True)
        state.event(True, '2026-11-19T00:00:01.000000000Z')
        self.assertIs(state.value, False)

    def test_reconnect_handoff_uses_welcome_before_closing_old_socket(self):
        clock, stop, operations = Clock(), Event(), []
        session = {'keepalive_timeout_seconds': 10}
        url = EVENTSUB + '?new=session'

        class Socket:
            def __init__(self, name, messages):
                self.name, self.messages = name, iter(messages)

            def recv(self):
                operations.append((self.name, 'recv'))
                reply = next(self.messages)
                if reply['metadata']['message_type'] == 'session_keepalive':
                    stop.set()
                return json.dumps(reply)

            def settimeout(self, seconds):
                pass

            def close(self, *, timeout):
                operations.append((self.name, 'close'))

        original = Socket('original', [{'metadata': {'message_type': 'session_reconnect'},
                                        'payload': {'session': {'reconnect_url': url}}}])
        replacement = Socket('replacement', [
            {'metadata': {'message_type': 'session_welcome'}, 'payload': {'session': session}},
            {'metadata': {'message_type': 'session_keepalive'}, 'payload': {}},
        ])

        def connect(address, **kwargs):
            self.assertEqual(address, url)
            return replacement

        result = Future()
        result.set_result({'data': [{}]})
        with TemporaryDirectory() as directory:
            chat = Chat(RIGS, clock=clock)
            twitch = Twitch('client', Path(directory), chat, clock=clock, connect=connect)
            twitch._listen(original, session, result, LiveState(), {}, 0, stop, 3600)
        self.assertEqual(operations, [
            ('original', 'recv'), ('replacement', 'recv'), ('original', 'close'),
            ('replacement', 'recv'), ('replacement', 'close'),
        ])
        self.assertIs(twitch.snapshot()['live'], True)

    def test_public_refresh_rotates_the_owner_only_credentials(self):
        calls = []

        def request(url, **kwargs):
            if url.endswith('/validate'):
                if kwargs['headers']['Authorization'] == 'OAuth expired':
                    raise TwitchError(401, 'invalid access token')
                return identity
            calls.append(kwargs['form'])
            return {'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 3600}

        identity = {'client_id': 'public-app', 'user_id': '123', 'login': 'pinball',
                    'expires_in': 3600, 'scopes': ['user:read:chat']}
        with TemporaryDirectory() as directory:
            path = Path(directory)
            twitch = Twitch('public-app', path, Chat(RIGS), http=request)
            auth = {'access_token': 'expired', 'refresh_token': 'original', 'user_id': '123',
                    'login': 'pinball', 'expires_at': 0}
            current, _ = twitch._credentials(auth, 0)
            self.assertEqual(current['refresh_token'], 'rotated')
            self.assertEqual(Twitch('public-app', path, Chat(RIGS)).auth, current)
            self.assertEqual((path / 'twitch-auth.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(calls, [{'client_id': 'public-app', 'grant_type': 'refresh_token',
                                  'refresh_token': 'original'}])
