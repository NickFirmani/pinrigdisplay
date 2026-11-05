"""VideoNode SSE consumer counts; unknown until every stream has a snapshot."""
import base64
import json
import logging
import time
from urllib.request import Request, urlopen
from .net import request_json

LOGGER = logging.getLogger(__name__)
RESYNC_SECONDS = 20.
MAX_EVENT = 65536


def events(stream):
    """Decode bounded SSE frames, including multiline data and comments."""
    name, data, size = 'message', [], 0
    while True:
        raw = stream.readline(MAX_EVENT + 1)
        if not raw:
            raise OSError('videonode event stream closed')
        size += len(raw)
        if size > MAX_EVENT:
            raise ValueError('videonode SSE frame too large')
        line = raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if data:
                yield name, json.loads('\n'.join(data))
            name, data, size = 'message', [], 0
        elif line.startswith('event:'):
            name = line[6:].lstrip(' ')
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))


class ConsumerSnapshot:
    """Track all streams on this rig; absent counts never imply zero."""
    def __init__(self, listing: object):
        if not isinstance(listing, dict) or not isinstance(listing.get('streams'), list):
            raise ValueError('videonode must return a streams list')
        self.counts = {}
        for item in listing['streams']:
            stream_id = item.get('stream_id') if isinstance(item, dict) else None
            if not isinstance(stream_id, str) or not stream_id or stream_id in self.counts:
                raise ValueError('invalid or duplicate videonode stream ID')
            self.counts[stream_id] = None

    def apply(self, name: str, value: object) -> bool:
        """Return whether this frame can renew the connection's evidence."""
        if not isinstance(value, dict):
            raise ValueError('invalid videonode event')
        if name == 'heartbeat':
            return True
        if name != 'entity':
            return False
        kind = value.get('type')
        if kind not in ('stream.consumers', 'stream.created', 'stream.deleted'):
            return False
        stream_id = value.get('id')
        if not isinstance(stream_id, str) or not stream_id:
            raise ValueError('invalid videonode event stream ID')
        if kind == 'stream.deleted':
            self.counts.pop(stream_id, None)
        elif kind == 'stream.created':
            self.counts[stream_id] = None
        else:
            payload = value.get('payload')
            count = payload.get('total') if isinstance(payload, dict) else None
            if type(count) is not int or count < 0:
                raise ValueError('invalid videonode consumer count')
            self.counts[stream_id] = count
        return True

    @property
    def active(self) -> bool | None:
        if any(count is not None and count > 0 for count in self.counts.values()):
            return True
        if any(count is None for count in self.counts.values()):
            return None
        return False


def run(url: str, authority, stop, *, credentials: str = '', clock=time.monotonic,
        get_json=request_json, open_stream=urlopen) -> None:
    """Reconnect regularly for full counts: SSE is best-effort and has no replay."""
    headers = {}
    if credentials:
        headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
    while not stop.is_set():
        try:
            snapshot = ConsumerSnapshot(get_json(url.rstrip('/') + '/api/streams', headers=headers))
            seeding = True
            request = Request(url.rstrip('/') + '/api/events',
                              headers={**headers, 'Accept': 'text/event-stream'})
            started = clock()
            with open_stream(request, timeout=18) as stream:
                for name, value in events(stream):
                    if stop.is_set() or clock() - started >= RESYNC_SECONDS:
                        break
                    if snapshot.apply(name, value):
                        # A planned resync must not replace good evidence with
                        # a partially received snapshot. Old evidence still ages.
                        if not seeding or snapshot.active is not None:
                            authority.observe_video(snapshot.active)
                        if all(count is not None for count in snapshot.counts.values()):
                            seeding = False
        except (OSError, ValueError) as error:
            LOGGER.warning('Videonode unavailable: %s', error)
            authority.observe_video(None)
            stop.wait(1)
        else:
            # VideoNode detects new subscribers by polling the total count once
            # per second. Let it observe our departure before reconnecting, or
            # idle streams may never re-emit their initial zero counts.
            stop.wait(2)
    authority.observe_video(None)
