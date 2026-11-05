"""Physical display integration check; uses HTTP and real delays, never unit discovery.

Run on the SPI-connected Pi: python3 tools/hardware_smoke.py
The display must be attended to assess appearance; API checks cannot verify pixels.
"""
import json
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

URL = 'http://127.0.0.1:48193/api/commands'


def send(operation, params=None, *, session=None, request_id=None):
    value = {'version': 1, 'request_id': request_id or uuid.uuid4().hex,
             'operation': operation, 'params': params or {}}
    if session:
        value['session'] = session
    request = Request(URL, json.dumps(value).encode(), {'Content-Type': 'application/json'})
    try:
        stream = urlopen(request, timeout=5)
    except HTTPError as error:
        stream = error
    with stream:
        return json.load(stream)


def main():
    session = send('hello')['result']['session']

    def command(operation, **params):
        reply = send(operation, params, session=session)
        assert reply['ok'], reply
        return reply['result']

    def status():
        result = command('status')
        assert result['healthy'], result
        assert result['display_fault'] is None, result
        return result

    initial = status()
    print('Initial state:', initial['displayed_state'], flush=True)
    for state in ('on_air', 'camera_active', 'camera_inactive'):
        command('set_state', state=state, lease_seconds=60, valid_for=60)
        time.sleep(4)
        result = status()
        assert result['displayed_state'] == state, result
        print(state, 'PASS; last frame write seconds:', result['last_render_seconds'], flush=True)

    command('set_state', state='on_air', lease_seconds=60, valid_for=60)
    time.sleep(1)
    rid = uuid.uuid4().hex
    params = {'title': 'DISPLAY TEST', 'body': 'Message opens below the sign, then expires.', 'duration': 3}
    first = send('show_message', params, session=session, request_id=rid)
    assert first['ok'], first
    assert send('show_message', params, session=session, request_id=rid) == first
    time.sleep(2)
    assert status()['visible_message']['message_id'] == rid
    command('set_state', state='camera_active', lease_seconds=60, valid_for=60)
    assert status()['displayed_state'] == 'camera_active'
    time.sleep(3)
    assert status()['recent_messages'][rid] == 'expired'
    print('Message transition, duplicate, concurrent state and expiry: PASS', flush=True)

    low = command('show_message', title='LOW PRIORITY', body='This card will be replaced.', duration=30)['message_id']
    time.sleep(2)
    high = command('show_message', title='HIGH PRIORITY', body='Higher priority replaced the previous card.', priority=9, duration=30)['message_id']
    assert status()['recent_messages'][low] == 'dropped'
    pending = [command('show_message', title='QUEUED', body=f'Pending message {i}', duration=3)['message_id'] for i in range(3)]
    overflow = send('show_message', {'title': 'OVERFLOW', 'body': 'Must be rejected'}, session=session)
    assert overflow['error']['code'] == 'queue_full', overflow
    command('cancel_message', message_id=pending[1])
    command('cancel_message', message_id=high)
    assert status()['visible_message']['message_id'] == pending[0]
    time.sleep(2)
    print('Priority, queue capacity, FIFO and cancellation: PASS', flush=True)

    ack = send('show_message', {'title': 'ACK', 'body': 'Touch capability check', 'requires_ack': True}, session=session)
    if status()['acknowledgment_available']:
        assert ack['ok'], ack
        command('cancel_message', message_id=ack['result']['message_id'])
    else:
        assert ack['error']['code'] == 'ack_unavailable', ack
    for mid in (pending[0], pending[2]):
        command('cancel_message', message_id=mid)
    retained = command('show_message', title='LEASE TEST', body='UNKNOWN must retain this message.', duration=30)['message_id']
    command('set_state', state='on_air', lease_seconds=2, valid_for=2)
    time.sleep(4)
    result = status()
    assert result['displayed_state'] == 'unknown', result
    assert result['visible_message']['message_id'] == retained, result
    command('cancel_message', message_id=retained)
    print('Lease expiry / UNKNOWN message retention / touch capability: PASS', flush=True)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
