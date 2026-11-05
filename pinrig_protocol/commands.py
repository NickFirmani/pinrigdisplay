"""Strict protocol v1 validation. Text is retained verbatim, never normalized."""
import math

VERSION = 1
MAX_FRAME = 8192
RETRY_SECONDS = 120
RETRY_CAPACITY = 512
STATES = frozenset({'on_air', 'camera_active', 'camera_inactive', 'unknown'})


class CommandError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CommandError('invalid_request', f'{name} must contain 1–{maximum} characters')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise CommandError('invalid_request', f'{name} contains control characters')
    return value


def identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or not all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-' for c in value):
        raise CommandError('invalid_request', f'{name} must be 1–64 ASCII letters, digits, or _ . : -')
    return value


def number(value: object, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise CommandError('invalid_request', f'{name} must be between {minimum} and {maximum}')
    return float(value)


class Command:
    """Dependency-free model, also deployed unchanged on MicroPython."""
    def __init__(self, request_id, operation, params, session=None):
        self.request_id = request_id
        self.operation = operation
        self.params = params
        self.session = session

    def __eq__(self, other):
        return isinstance(other, Command) and self.to_dict() == other.to_dict()

    @classmethod
    def parse(cls, value: object) -> 'Command':
        if not isinstance(value, dict) or set(value) - {'version', 'request_id', 'operation', 'params', 'session'}:
            raise CommandError('invalid_request', 'expected a command object with known fields')
        if type(value.get('version')) is not int or value['version'] != VERSION:
            raise CommandError('unsupported_version', 'protocol version must be 1')
        request_id = identifier(value.get('request_id'), 'request_id')
        op = value.get('operation')
        fields = {'hello': set(), 'status': set(),
                  'set_state': {'state', 'diagnostic', 'lease_seconds', 'valid_for'},
                  'show_message': {'title', 'body', 'duration', 'priority', 'requires_ack'},
                  'cancel_message': {'message_id'}, 'confirm_interaction': {'interaction_id'}}
        if not isinstance(op, str) or op not in fields:
            raise CommandError('invalid_request', 'unsupported operation')
        params = value.get('params', {})
        if not isinstance(params, dict) or set(params) - fields[op]:
            raise CommandError('invalid_request', 'unknown parameters')
        p = dict(params)
        if op == 'set_state':
            if not isinstance(p.get('state'), str) or p['state'] not in STATES:
                raise CommandError('invalid_request', 'unsupported state')
            p['lease_seconds'] = number(p.get('lease_seconds', 15), 'lease_seconds', 1, 60)
            p['valid_for'] = number(p.get('valid_for', 30), 'valid_for', 1, 300)
            p['diagnostic'] = text(p.get('diagnostic', 'Waiting for current state'), 'diagnostic', 120)
        elif op == 'show_message':
            p['title'] = text(p.get('title'), 'title', 40)
            p['body'] = text(p.get('body'), 'body', 240)
            p['duration'] = number(p.get('duration', 8), 'duration', 1, 300)
            p['priority'] = p.get('priority', 0)
            if type(p['priority']) is not int or not 0 <= p['priority'] <= 9:
                raise CommandError('invalid_request', 'priority must be an integer from 0 to 9')
            p['requires_ack'] = p.get('requires_ack', False)
            if type(p['requires_ack']) is not bool:
                raise CommandError('invalid_request', 'requires_ack must be boolean')
        elif op in ('cancel_message', 'confirm_interaction'):
            key = 'message_id' if op == 'cancel_message' else 'interaction_id'
            p[key] = identifier(p.get(key), key)
        session = value.get('session')
        if op not in ('hello', 'status'):
            session = identifier(session, 'session (from hello)')
        elif session is not None:
            session = identifier(session, 'session')
        return cls(request_id, op, p, session)

    def to_dict(self) -> dict:
        result = {'version': VERSION, 'request_id': self.request_id,
                  'operation': self.operation, 'params': dict(self.params)}
        if self.session is not None:
            result['session'] = self.session
        return result


def response(request_id: str | None, result: dict) -> dict:
    return {'version': VERSION, 'request_id': request_id, 'ok': True, 'result': result}


def error_response(request_id: str | None, code: str, message: str) -> dict:
    return {'version': VERSION, 'request_id': request_id, 'ok': False,
            'error': {'code': code, 'message': message}}
