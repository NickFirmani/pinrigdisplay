"""Bounded JSON HTTP calls for producer integrations."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MAX_RESPONSE = 1024 * 1024


def read_json(stream):
    raw = stream.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('HTTP response too large')
    return json.loads(raw)


def request_json(url: str, value: dict | None = None, *, headers=None, timeout=2.):
    body = None if value is None else json.dumps(value, allow_nan=False).encode()
    request = Request(url, body, {'Content-Type': 'application/json', **(headers or {})})
    try:
        stream = urlopen(request, timeout=timeout)
    except HTTPError as error:
        stream = error
    with stream:
        result = read_json(stream)
        if stream.status >= 400:
            raise OSError(f'HTTP {stream.status}: {result}')
        return result
