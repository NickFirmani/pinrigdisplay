"""Small producer HTTP client; no external service clients or backlog."""
import json
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class Client:
    def __init__(self, url: str, *, timeout: float = 3.):
        self.url = url.rstrip('/') + '/api/commands'
        self.timeout = timeout
        self.session = None

    def _send(self, operation, params, request_id):
        body = {'version': 1, 'request_id': request_id, 'operation': operation,
                'params': params}
        if self.session:
            body['session'] = self.session
        req = Request(self.url, json.dumps(body).encode(), {'Content-Type': 'application/json'})
        try:
            stream = urlopen(req, timeout=self.timeout)
        except HTTPError as error:
            stream = error
        with stream:
            return json.load(stream)

    def send(self, operation: str, params: dict, *, request_id: str | None = None) -> dict:
        """Never automatically replay a transient command following an error."""
        if self.session is None:
            hello = self._send('hello', {}, uuid.uuid4().hex)
            if not hello['ok']:
                return hello
            self.session = hello['result']['session']
        result = self._send(operation, params, request_id or uuid.uuid4().hex)
        if not result['ok'] and result['error']['code'] == 'session_changed':
            self.session = None
        return result
