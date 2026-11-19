"""Translate display command failures into rig HTTP response statuses."""

COMMAND_ERROR_CODES = {'invalid_request': 422, 'unsupported_version': 422, 'invalid_frame': 400,
         'request_conflict': 409, 'session_changed': 409, 'queue_full': 429,
         'retry_capacity': 429, 'not_found': 404, 'ack_unavailable': 422}
