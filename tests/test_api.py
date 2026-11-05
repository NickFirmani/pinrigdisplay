"""HTTP handler tests use in-memory streams: no socket, network or timing."""
import io
from email.message import Message
import json
import unittest
from pinrig_protocol.http import make_handler
from display_controller.serial import SerialEndpoint
from pinrig_protocol.framing import Framer, encode
from tests.helpers import device, command


def http(endpoint, value=None, *, raw=None, length=None):
    raw = json.dumps(value).encode() if raw is None else raw
    cls = make_handler(endpoint)
    h = object.__new__(cls)
    h.path = '/api/commands'
    h.headers = Message()
    h.headers['Content-Type'] = 'application/json'
    h.headers['Content-Length'] = str(len(raw) if length is None else length)
    h.rfile = io.BytesIO(raw); h.wfile = io.BytesIO()
    codes = []
    h.send_response = codes.append
    h.send_header = lambda *args: None
    h.end_headers = lambda: None
    h.do_POST()
    return codes[0], json.loads(h.wfile.getvalue())


class APITests(unittest.TestCase):
    def test_local_http_serial_parity(self):
        controllers = [device()[0] for _ in range(3)]
        for request in [command('hello'), command('set_state', state='on_air'),
                        command('show_message', 'msg', title='T', body='B'),
                        command('show_message', 'msg', title='T', body='B'),
                        command('cancel_message', 'cancel', message_id='msg'), command('status')]:
            local = controllers[0].handle(request)
            code, reply = http(controllers[1], request)
            serial = json.loads(SerialEndpoint(controllers[2]).feed(encode(request)))
            self.assertEqual(code, 200)
            self.assertEqual(local, reply)
            self.assertEqual(local, serial)

    def test_bad_http_and_bounded_body(self):
        c = device()[0]
        self.assertEqual(http(c, raw=b'{')[0], 400)
        self.assertEqual(http(c, raw=b'{}', length=8193)[0], 413)
        self.assertEqual(http(c, raw=b'{}', length=8)[0], 400)
        self.assertEqual(http(c, command('bad'))[0], 422)

    def test_partial_utf8_and_multiple_frames(self):
        f = Framer(); data = encode(command('show_message', title='é', body='B'))
        results = []
        for byte in data: results += f.feed(bytes([byte]))
        self.assertEqual(results, [command('show_message', title='é', body='B')])
        self.assertEqual(len(f.feed(data + data)), 2)

    def test_recovers_after_bad_and_oversized_frames(self):
        f = Framer()
        self.assertEqual(f.feed(b'x'*9000), [])
        self.assertEqual(len(f.buffer), 0)
        results = f.feed(b'ignored\n\xff\n[]\n' + encode(command('hello')))
        self.assertEqual([r['error']['code'] for r in results[:3]], ['invalid_frame'] * 3)
        self.assertEqual(results[3]['operation'], 'hello')

    def test_untrusted_error_field_does_not_bypass_validation(self):
        c = device()[0]; endpoint = SerialEndpoint(c)
        for value in ({'error': None}, {'error': {'code': 'invalid_frame'}, 'request_id': 'malicious'}):
            reply = json.loads(endpoint.feed(encode(value)))
            self.assertEqual(reply['error']['code'], 'invalid_request')

    def test_deeply_nested_json_is_rejected_and_recovers(self):
        f = Framer()
        results = f.feed(b'['*1200 + b']'*1200 + b'\n' + encode(command('hello')))
        self.assertEqual(results[0]['error']['code'], 'invalid_frame')
        self.assertEqual(results[1]['operation'], 'hello')
