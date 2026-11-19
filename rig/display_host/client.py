"""In-process commands for a rig that owns its USB host."""
import uuid
from .service import Host


class LocalClient:
    """Use the host's validation/deduplication without HTTP or automatic replay."""
    def __init__(self, host: Host):
        self.host = host

    def send(self, operation: str, params: dict, *, request_id: str | None = None) -> dict:
        return self.host.handle({'version': 1, 'request_id': request_id or uuid.uuid4().hex,
            'session': self.host.session, 'operation': operation, 'params': params})
