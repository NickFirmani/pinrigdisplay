"""Serialized device command handling, leases, message scheduling and rendering."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import logging
import threading
import time
import uuid
from typing import Callable, Protocol
from PIL import Image

from pinrig_protocol.commands import (Command, CommandError, RETRY_SECONDS,
                                      RETRY_CAPACITY, response, error_response)
from .display.renderer import Frame, encode_rgb565

LOGGER = logging.getLogger(__name__)


class Display(Protocol):
    def initialize(self) -> None: ...
    def write(self, frame: Frame, *, x: int = 0, y: int = 0) -> None: ...
    def close(self) -> None: ...


class Renderer(Protocol):
    def compose(self, state: str, message: dict | None, diagnostic: str,
                sign_height: int, seconds: float) -> Image.Image: ...


@dataclass
class Message:
    id: str
    params: dict
    order: int
    status: str = 'pending'
    expires: float | None = None


class DisplayController:
    def __init__(self, *, display: Display, pages: Renderer, clock: Callable[[], float] = time.monotonic,
                 session: str | None = None, transition_seconds: float = .5, interactions=None) -> None:
        if not 0 <= transition_seconds <= 2:
            raise ValueError("transition_seconds must be between 0 and 2")
        self.interactions = interactions
        self.touch_available = interactions is not None
        self.touch_fault = None
        self.touch_released = False
        self.touch_target = None
        self.display = display
        self.pages = pages
        self.clock = clock
        self.session = session or uuid.uuid4().hex
        self.transition_seconds = transition_seconds
        self.lock = threading.RLock()
        self.requested = 'unknown'
        self.displayed = None
        self.diagnostic = 'Waiting for current state'
        self.revision = 0
        self.displayed_revision = 0
        self.lease_until = None
        self.visible = None
        self.pending = []
        self.history = OrderedDict()
        self.cache = OrderedDict()
        self.fault = None
        self.closed = False
        self.height = 320.0
        self.start_height = self.height
        self.target_height = self.height
        self.transition_at = clock()
        self.animation_seconds = 0.0
        self.animation_updated_at = self.transition_at
        self.layout_was_moving = False
        self.last_image = None
        self.last_render_seconds = 0.0

    def start(self) -> None:
        with self.lock:
            try:
                self.display.initialize()
                self._render(self.clock())
            except Exception:
                self.display.close()
                self.closed = True
                raise

    def close(self) -> None:
        with self.lock:
            if not self.closed:
                self.closed = True
                self.display.close()

    def handle(self, value: object) -> dict:
        request_id = value.get('request_id') if isinstance(value, dict) else None
        if not isinstance(request_id, str) or len(request_id) > 64:
            request_id = None
        with self.lock:
            try:
                cmd = Command.parse(value)
                now = self.clock()
                self._advance(now)
                if self.closed:
                    raise CommandError('unavailable', 'device is closed')
                if cmd.operation == 'hello':
                    return response(cmd.request_id, {'session': self.session,
                        'retry_seconds': RETRY_SECONDS, 'retry_capacity': RETRY_CAPACITY,
                        'acknowledgment_available': self.touch_available, 'max_pending': 3})
                if cmd.operation == 'status':
                    return response(cmd.request_id, self.status())
                if cmd.session != self.session:
                    raise CommandError('session_changed', 'handshake required; do not replay transient messages')
                for key, entry in list(self.cache.items()):
                    if now - entry[0] >= RETRY_SECONDS:
                        del self.cache[key]
                canonical = cmd.to_dict()
                if cmd.request_id in self.cache:
                    _, previous, result = self.cache[cmd.request_id]
                    if previous != canonical:
                        raise CommandError('request_conflict', 'request ID already used with different content')
                    return deepcopy(result)
                if len(self.cache) >= RETRY_CAPACITY:
                    raise CommandError('retry_capacity', 'retry window full; try later with a new request ID')
                try:
                    result = self._apply(cmd, now)
                    self._render(now)
                    reply = response(cmd.request_id, {**result, 'accepted': True,
                        'display_success': self.fault is None, 'display_fault': self.fault})
                except CommandError as error:
                    reply = error_response(cmd.request_id, error.code, str(error))
                self.cache[cmd.request_id] = (now, canonical, deepcopy(reply))
                return reply
            except CommandError as error:
                return error_response(request_id, error.code, str(error))

    def _apply(self, cmd, now):
        p = cmd.params
        if cmd.operation == 'set_state':
            self.revision += 1
            self.requested = p['state']
            self.diagnostic = p['diagnostic']
            self.lease_until = now + min(p['lease_seconds'], p['valid_for'])
            self._layout(now)
            return {'revision': self.revision}
        if cmd.operation == 'show_message':
            if p['requires_ack'] and not self.touch_available:
                raise CommandError('ack_unavailable', 'touch acknowledgment is not available')
            if self.visible and p['priority'] <= self.visible.params['priority'] and len(self.pending) >= 3:
                raise CommandError('queue_full', 'at most three messages may be pending')
            msg = Message(cmd.request_id, p, self.revision)
            self.revision += 1
            if self.visible and p['priority'] > self.visible.params['priority']:
                self._finish(self.visible, 'dropped')
                self.visible = None
            if self.visible is None:
                self.visible = msg
                msg.status = 'opening'
            else:
                self.pending.append(msg)
            self._layout(now)
            return {'message_id': msg.id, 'text_policy': 'verbatim; visual overflow uses ellipsis'}
        if cmd.operation == 'cancel_message':
            mid = p['message_id']
            if self.visible and self.visible.id == mid:
                self._finish(self.visible, 'cancelled')
                self.visible = None
            else:
                match = next((m for m in self.pending if m.id == mid), None)
                if match:
                    self.pending.remove(match)
                    self._finish(match, 'cancelled')
                elif mid not in self.history:
                    raise CommandError('not_found', 'unknown message ID')
            self._next(now)
            return {'message_id': mid, 'status': self.history[mid]}
        if cmd.operation == 'confirm_interaction' and self.interactions is not None:
            try:
                self.interactions.confirm(p['interaction_id'])
            except Exception as error:
                raise CommandError('unavailable', f'interaction confirmation failed: {error}') from error
            return {'interaction_id': p['interaction_id'], 'confirmed': True}
        raise CommandError('ack_unavailable', 'no touch interactions are supported')

    def _finish(self, message, status):
        self.touch_target = None
        self.history[message.id] = status
        while len(self.history) > 32:
            self.history.popitem(last=False)

    def _next(self, now):
        if self.visible is None and self.pending:
            self.pending.sort(key=lambda m: (-m.params['priority'], m.order))
            self.visible = self.pending.pop(0)
            self.visible.status = 'opening'
        self._layout(now)

    def _geometry(self, now):
        fraction = min(1., max(0., (now - self.transition_at) / self.transition_seconds)) if self.transition_seconds else 1.
        eased = fraction * fraction * (3 - 2 * fraction)
        return self.start_height + (self.target_height - self.start_height) * eased

    def _layout(self, now):
        target = 188. if self.visible else 320.
        if target != self.target_height:
            self.touch_target = None
            self.start_height = self._geometry(now)
            self.transition_at = now
            self.target_height = target

    def _advance(self, now):
        if self.lease_until is not None and now >= self.lease_until:
            self.lease_until = None
            self.requested = 'unknown'
            self.diagnostic = 'Host command lease expired'
            self.revision += 1
            self._layout(now)
        if self.visible and self.visible.expires is not None and now >= self.visible.expires:
            self._finish(self.visible, 'expired')
            self.visible = None
            self._next(now)

    def touch_failed(self, reason: str) -> None:
        with self.lock:
            self.touch_available = False
            self.touch_target = None
            self.touch_fault = reason[:120]
            self._render(self.clock())

    def touch(self, pressed: bool) -> None:
        """Bind a fresh press/release to one fully rendered, stationary card."""
        with self.lock:
            now = self.clock()
            self._advance(now)
            if self.closed or not self.touch_available:
                return
            if pressed:
                target = self.visible
                stable = abs(self._geometry(now) - self.target_height) < .01
                self.touch_target = (target.id if self.touch_released and target and
                    target.status == 'visible' and stable and self.fault is None else None)
                self.touch_released = False
                return
            self.touch_released = True
            target_id, self.touch_target = self.touch_target, None
            if not self.visible or self.visible.id != target_id:
                return
            msg = self.visible
            kind = 'acknowledged' if msg.params['requires_ack'] else 'dismissed'
            interaction = {'interaction_id': uuid.uuid4().hex, 'message_id': msg.id,
                           'session': self.session, 'kind': kind}
            try:
                self.interactions.append(interaction)
            except Exception as error:
                self.touch_fault = str(error)[:120]
                LOGGER.exception('Could not persist touch interaction')
                self._render(now)
                return
            self.touch_fault = None
            self._finish(msg, kind)
            self.visible = None
            self._next(now)
            self._render(now)

    def frame_interval(self, animation_fps: int) -> float:
        """Give layout changes a faster cadence; the SPI transfer bounds throughput."""
        with self.lock:
            moving = abs(self._geometry(self.clock()) - self.target_height) > .01
            return 1 / (30 if moving else animation_fps)

    def tick(self) -> None:
        """Advance from an injected monotonic clock; runtime owns the timer."""
        with self.lock:
            if not self.closed:
                now = self.clock()
                self._advance(now)
                self._render(now)

    def _render(self, now):
        try:
            self.height = self._geometry(now)
            moving = abs(self.height - self.target_height) > .01
            # Freeze the current pulse phase, rather than resetting brightness
            # during scaling and jumping back to wall-clock phase afterward.
            # The final layout frame stays frozen too; motion resumes next frame.
            if not moving and not self.layout_was_moving and self.visible is None:
                self.animation_seconds += max(0., now - self.animation_updated_at)
            self.animation_updated_at = now
            self.layout_was_moving = moving
            card = dict(self.visible.params) if self.visible else None
            if card and self.touch_fault:
                card['title'] = 'TOUCH ACK FAILED'
                card['body'] = self.touch_fault + '. Message retained; try again.'
            elif card and card['requires_ack']:
                card['title'] = 'TAP TO ACK: ' + card['title']
            image = self.pages.compose(self.requested, card,
                self.diagnostic, round(self.height), self.animation_seconds)
            # Region writes reduce SPI traffic; skip unchanged frames entirely.
            from PIL import ImageChops
            region = ImageChops.difference(image, self.last_image).getbbox() if self.last_image is not None else (0, 0, image.width, image.height)
            started = self.clock()
            if region:
                self.display.write(encode_rgb565(image.crop(region)), x=region[0], y=region[1])
            self.last_render_seconds = self.clock() - started
            self.last_image = image
            self.displayed = self.requested
            self.displayed_revision = self.revision
            self.fault = None
            if self.visible and self.visible.status == 'opening' and not moving:
                self.visible.status = 'visible'
                self.visible.expires = (None if self.visible.params['requires_ack'] else
                                        self.clock() + self.visible.params['duration'])
        except Exception as error:
            self.fault = str(error)[:240]
            self.last_image = None
            LOGGER.exception('Display render failed')

    def _pending_interactions(self) -> list[dict]:
        if self.interactions is None:
            return []
        try:
            return self.interactions.pending()
        except Exception as error:
            reason = f'Cannot read acknowledgment outbox: {error}'[:120]
            if self.touch_fault != reason:
                LOGGER.exception('Could not read touch interaction outbox')
            self.touch_fault = reason
            self.touch_available = False
            self.touch_target = None
            return []

    def status(self) -> dict:
        with self.lock:
            interactions = self._pending_interactions()
            return {'session': self.session, 'requested_state': self.requested,
                'displayed_state': self.displayed, 'revision': self.revision,
                'displayed_revision': self.displayed_revision, 'display_fault': self.fault,
                'healthy': not self.closed and self.fault is None and self.displayed is not None,
                'diagnostic': self.diagnostic if self.requested == 'unknown' else None,
                'visible_message': ({'message_id': self.visible.id, 'status': self.visible.status}
                                    if self.visible else None),
                'pending': [m.id for m in self.pending], 'queue_depth': len(self.pending),
                'recent_messages': dict(self.history), 'acknowledgment_available': self.touch_available,
                'interactions': interactions,
                'touch_fault': self.touch_fault, 'last_render_seconds': self.last_render_seconds}
