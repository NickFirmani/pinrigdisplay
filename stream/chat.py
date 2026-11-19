"""Group live Twitch chat and deliver independently to idle rig displays."""
from collections import OrderedDict
from dataclasses import dataclass
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from shared.net import read_json

GROUP_SECONDS = 3
GROUP_MESSAGES = 3
CARD_SECONDS = 8
FRESH_SECONDS = 15
TITLE_LIMIT = 40
BODY_LIMIT = 240
DEDUP_SECONDS = 600
DEDUP_CAPACITY = 4096


def display_text(value: str, limit: int) -> str:
    value = ''.join(c for c in value if ord(c) >= 32 or c in '\n\t').strip()
    return value if len(value) <= limit else value[:limit - 3] + '...'


@dataclass(frozen=True)
class Card:
    title: str
    body: str
    started: float
    request_id: str
    test: bool = False


@dataclass
class Group:
    user: str
    title: str
    started: float
    targets: set[str]
    messages: list[str]


@dataclass
class Destination:
    enabled: bool = True
    healthy: bool = False
    booth: bool = False
    checked: float = float('-inf')
    pending: Card | None = None
    visible: str | None = None
    visible_generation: int = 0
    retry_at: float = 0
    generation: int = 0
    outcome: str | None = None


def rig_request(rig: dict, path: str, payload: dict) -> dict:
    request = Request(rig['url'].rstrip('/') + path, json.dumps(payload).encode(),
                      {'Content-Type': 'application/json'})
    try:
        reply = urlopen(request, timeout=3)
    except HTTPError as error:
        reply = error
    with reply:
        value = read_json(reply)
    if not isinstance(value, dict):
        raise ValueError('invalid rig response')
    return value


class Chat:
    def __init__(self, rigs, *, clock=time.monotonic, post=rig_request):
        self.clock, self.post = clock, post
        self.lock = threading.Lock()
        self.targets = {rig['id']: Destination() for rig in rigs}
        self.seen = OrderedDict()
        self.group = None
        self.authorized = False
        self.live = None

    def _invalidate(self, rig_id, *, keep_test=False):
        target = self.targets[rig_id]
        if not (keep_test and target.pending and target.pending.test):
            target.pending = None
        target.generation += 1
        if self.group:
            self.group.targets.discard(rig_id)

    def channel(self, authorized: bool, live: bool | None) -> None:
        with self.lock:
            previous = self.authorized, self.live
            self.authorized, self.live = authorized, live
            if previous != (authorized, live) and (not authorized or live is not True):
                self.group = None
                for rig_id in self.targets:
                    self._invalidate(rig_id, keep_test=authorized)

    def enable(self, rig_id: str, enabled: bool) -> None:
        with self.lock:
            target = self.targets[rig_id]
            target.enabled = enabled
            if not enabled:
                self._invalidate(rig_id)

    def report(self, rig_id: str, status: dict) -> None:
        with self.lock:
            target = self.targets[rig_id]
            now = self.clock()
            was_eligible = self._eligible(target, now)
            target.healthy = status.get('healthy') is True
            target.booth = status.get('booth') is True
            target.checked = now
            if not self._eligible(target, now) or not was_eligible:
                if was_eligible or target.pending is not None:
                    self._invalidate(rig_id)
                elif self.group:
                    self.group.targets.discard(rig_id)

    def _eligible(self, target, now):
        return (self.authorized and target.enabled and target.healthy
                and now - target.checked <= 6 and not target.booth)

    def _flush(self, now):
        group, self.group = self.group, None
        if group is None or now - group.started >= FRESH_SECONDS:
            return
        card = Card(group.title, '\n'.join(group.messages), group.started, 'chat-' + uuid4().hex)
        for rig_id in group.targets:
            target = self.targets[rig_id]
            if self.live is True and self._eligible(target, now):
                target.pending = card

    def receive(self, notification: str, user: str, name: str, body: str) -> None:
        title, body = display_text(name, TITLE_LIMIT), display_text(body, BODY_LIMIT)
        now = self.clock()
        with self.lock:
            while self.seen and next(iter(self.seen.values())) <= now - DEDUP_SECONDS:
                self.seen.popitem(last=False)
            if notification in self.seen:
                return
            self.seen[notification] = now
            if len(self.seen) > DEDUP_CAPACITY:
                self.seen.popitem(last=False)
            targets = {key for key, target in self.targets.items() if self._eligible(target, now)}
            if not targets or self.live is not True or not title or not body:
                return
            group = self.group
            if group and (group.user != user or now - group.started >= GROUP_SECONDS
                          or len('\n'.join([*group.messages, body])) > BODY_LIMIT
                          or not targets <= group.targets):
                self._flush(now)
                group = None
            if group is None:
                group = self.group = Group(user, title, now, targets, [])
            group.targets.intersection_update(targets)
            group.messages.append(body)
            if len(group.messages) >= GROUP_MESSAGES:
                self._flush(now)

    def test(self, rig_id: str) -> None:
        with self.lock:
            target = self.targets[rig_id]
            now = self.clock()
            if not self._eligible(target, now):
                raise ValueError('Connect Twitch and select an enabled rig with a healthy display and no booth message.')
            target.pending = Card('Twitch chat', 'Test message from the stream PC', now,
                                  'chat-' + uuid4().hex, test=True)
            target.outcome = 'Test card waiting'

    def outcome(self, rig_id: str) -> str | None:
        with self.lock:
            return self.targets[rig_id].outcome

    def step(self, rig: dict, *, closing=False) -> None:
        """One delivery or cancellation. Only the rig's own worker calls this."""
        now = self.clock()
        with self.lock:
            if self.group and now - self.group.started >= GROUP_SECONDS:
                self._flush(now)
            target = self.targets[rig['id']]
            cancel = target.visible if closing or not target.enabled or not self.authorized else None
            card = target.pending
            if cancel is None and target.visible and target.generation != target.visible_generation:
                cancel = target.visible
            if cancel:
                target.visible = None
            else:
                if closing or card is None:
                    return
                if now - card.started >= FRESH_SECONDS:
                    target.pending = None
                    target.outcome = 'Skipped: card expired'
                    return
                if not self._eligible(target, now) or (not card.test and self.live is not True):
                    target.pending = None
                    return
                if now < target.retry_at:
                    return
                target.pending = None
                generation = target.generation
        if cancel:
            try:
                reply = self.post(rig, '/api/chat/cancel', {'message_id': cancel})
                outcome = 'Chat cancelled' if reply.get('ok') else 'Cancellation unconfirmed'
            except (OSError, ValueError):
                outcome = 'Cancellation unconfirmed'
            with self.lock:
                target.outcome = outcome
            return
        try:
            reply = self.post(rig, '/api/chat', {'title': card.title, 'body': card.body,
                                               'request_id': card.request_id})
            error = reply.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            result = reply.get('result')
            confirmed = (reply.get('ok') is True and isinstance(result, dict)
                         and result.get('message_id') == card.request_id
                         and result.get('display_success') is not False)
        except (OSError, ValueError):
            code, confirmed = None, False
        with self.lock:
            if code == 'chat_busy':
                if target.pending is None and target.generation == generation:
                    target.pending = card
                target.retry_at = self.clock() + 1
                target.outcome = 'Waiting for visible chat'
            elif code == 'booth_busy':
                target.booth = True
                self._invalidate(rig['id'])
                target.outcome = 'Skipped: booth message active'
            else:
                # Keep even an uncertain ID for targeted cancellation. Never resend it.
                if confirmed or code in (None, 'delivery_uncertain'):
                    target.visible = card.request_id
                    target.visible_generation = generation
                    target.retry_at = self.clock() + CARD_SECONDS
                target.outcome = ('Test card delivered' if card.test else 'Chat delivered') if confirmed else (
                    'Delivery unconfirmed' if code in (None, 'delivery_uncertain') else 'Display unavailable')

    def run_rig(self, rig: dict, stop: threading.Event) -> None:
        while not stop.is_set():
            self.step(rig)
            stop.wait(.2)
        self.step(rig, closing=True)
