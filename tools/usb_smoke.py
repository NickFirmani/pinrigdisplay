"""Attended rig API → USB check. Run with OBS reporting paused and no booth cards."""
import argparse
import os
import time
import uuid

from pinrig_producers.net import request_json


def check_rig(url: str, rig: str, *, token: str = '', request=request_json,
              clock=time.monotonic, delay=time.sleep, timeout: float = 10.) -> None:
    """Check status, OBS ingestion, persistent booth cards and cancellation.

    Uses real network/time by default. Cancels only its own card on exit.
    Physical pixels and touch still require attended inspection.
    """
    base = url.rstrip('/')
    headers = {'Authorization': 'Bearer ' + token} if token else {}

    def call(path, value=None):
        result = request(base + path, value, headers=headers)
        if result.get('ok') is False:
            raise RuntimeError(f'{path}: {result}')
        return result

    def device():
        status = call('/api/status')
        if status['rig'] != rig:
            raise RuntimeError(f'expected {rig}, received {status["rig"]}')
        host = status['host']
        if not host.get('ok') or not host['result']['connected']:
            raise RuntimeError(f'device disconnected: {host}')
        result = host['result']['device']
        if not result['healthy']:
            raise RuntimeError(f'device unhealthy: {result}')
        return result

    def wait_for(predicate):
        deadline = clock() + timeout
        while True:
            status = device()
            if predicate(status):
                return
            if clock() >= deadline:
                raise RuntimeError(f'rig did not reach expected state: {status}')
            delay(.2)

    initial = device()
    if initial['visible_message'] or initial['pending']:
        raise RuntimeError('clear existing booth cards before running the smoke check')
    mid = 'booth-smoke-' + uuid.uuid4().hex[:12]
    try:
        call('/api/obs', {'rig': rig, 'live': True, 'valid_for': 8})
        wait_for(lambda s: s['displayed_state'] == 'on_air')
        call('/api/messages', {'body': 'Rig API smoke check — clear follows shortly.',
                               'request_id': mid})
        wait_for(lambda s: s['visible_message'] is not None and
                 s['visible_message']['message_id'] == mid)
        call('/api/obs', {'rig': rig, 'live': None, 'valid_for': 8})
        wait_for(lambda s: s['displayed_state'] == 'unknown' and
                 s['visible_message'] is not None and
                 s['visible_message']['message_id'] == mid)
    finally:
        try:
            call('/api/clear', {'message_id': mid})
        finally:
            call('/api/obs', {'rig': rig, 'live': None, 'valid_for': 8})
    wait_for(lambda s: s['visible_message'] is None and mid not in s['pending'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:48194')
    parser.add_argument('--rig', choices=('rig1', 'rig2'), required=True)
    args = parser.parse_args()
    check_rig(args.url, args.rig, token=os.environ.get('PINRIG_OBS_TOKEN', ''))
    print('PASS: rig status, OBS ingestion, USB delivery, UNKNOWN retention and booth clear.')
    print('Inspect physical pixels and test real taps separately; resume OBS reporting.')


if __name__ == '__main__':
    main()
