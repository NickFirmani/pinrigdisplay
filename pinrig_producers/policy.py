"""First observation contract: per-rig evidence resolved by one upstream authority.

Adapters must resolve nested scenes, transitions and output composition before
emitting evidence. None means unknown, never negative evidence.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Observation:
    source: str
    rig: str
    observed_at: float
    live: bool | None
    local_use: bool | None

    def __post_init__(self):
        if not self.source or not self.rig or not math.isfinite(self.observed_at):
            raise ValueError('observation requires source, rig and finite observation time')
        if any(v is not None and type(v) is not bool for v in (self.live, self.local_use)):
            raise ValueError('evidence must be true, false or unknown')


@dataclass(frozen=True)
class Resolution:
    state: str
    reason: str


def resolve(observations: list[Observation], *, rig: str, required_sources: set[str],
            now: float, max_age: float) -> Resolution:
    """Resolve only fresh evidence for this rig; live confirmation wins."""
    if not required_sources or not math.isfinite(max_age) or max_age <= 0 or not math.isfinite(now):
        raise ValueError('explicit required sources and a positive freshness limit are required')
    latest = {}
    for obs in observations:
        if obs.rig == rig and obs.source in required_sources and 0 <= now - obs.observed_at <= max_age:
            previous = latest.get(obs.source)
            if previous is None or obs.observed_at > previous.observed_at:
                latest[obs.source] = obs
            elif obs.observed_at == previous.observed_at and obs != previous:
                latest[obs.source] = Observation(obs.source, rig, obs.observed_at, None, None)
    values = list(latest.values())
    if any(o.live is True for o in values):
        return Resolution('on_air', 'Confirmed live contribution for this rig')
    if set(latest) != required_sources or any(o.live is None for o in values):
        return Resolution('unknown', 'Live evidence missing or stale')
    if any(o.local_use is True for o in values):
        return Resolution('camera_active', 'Confirmed local use')
    if any(o.local_use is None for o in values):
        return Resolution('unknown', 'Local-use evidence missing')
    return Resolution('camera_inactive', 'All required sources confirm no use')


class Selection:
    """Manual game/player selection overrides automatic values until cleared."""
    def __init__(self):
        self.manual = None
        self.automatic = None

    @property
    def value(self):
        return self.manual if self.manual is not None else self.automatic


def notice(*, title: str, body: str, observed_at: float, now: float,
           max_age: float, priority: int = 0, duration: float = 8,
           moderated: bool = True) -> dict | None:
    """Drop stale/unmoderated upstream notices without accumulating a backlog."""
    if not all(math.isfinite(x) for x in (observed_at, now, max_age)) or max_age <= 0:
        raise ValueError('invalid notice freshness')
    if not moderated or not 0 <= now - observed_at <= max_age:
        return None
    from pinrig_protocol import Command
    return Command.parse({'version': 1, 'request_id': 'validate', 'session': 'validate',
        'operation': 'show_message', 'params': {'title': title, 'body': body,
        'priority': priority, 'duration': duration, 'requires_ack': False}}).params
