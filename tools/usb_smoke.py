"""Attended HTTP→USB hardware checks. Uses real time/network; not a unit test."""
import argparse
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Client:
    def __init__(self,url):
        self.url=url.rstrip('/')+'/api/commands'
        self.session=None
        self.session=self.call('hello')['session']

    def call(self,operation,params=None,request_id=None,error=None):
        rid=request_id or uuid.uuid4().hex
        value={'version':1,'request_id':rid,'operation':operation,'params':params or {}}
        if self.session:value['session']=self.session
        for _ in range(30):
            request=Request(self.url,json.dumps(value).encode(),{'Content-Type':'application/json'})
            try:stream=urlopen(request,timeout=5)
            except HTTPError as e:stream=e
            with stream:reply=json.load(stream)
            if reply['ok']:
                assert error is None,reply
                return reply['result']
            if reply['error']['code']==error:return reply
            if reply['error']['code']!='unavailable':raise RuntimeError(reply)
            time.sleep(.2)
        raise RuntimeError(reply)

    def device(self):
        result=self.call('status')
        assert result['connected'],result
        assert result['device']['healthy'],result
        return result['device']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://localhost:48193')
    args=parser.parse_args();client=Client(args.url)
    prefix=uuid.uuid4().hex[:12]
    client.call('set_state',{'state':'camera_active','lease_seconds':15,'valid_for':60})
    def message(name,priority=0):
        return client.call('show_message',{'title':'USB QUEUE TEST','body':name,
                          'duration':30,'priority':priority},prefix+'-'+name)
    first=message('visible',9)
    assert message('visible',9)==first
    for name in ('p1','p2','p3'):message(name)
    client.call('show_message',{'title':'OVERFLOW','body':'Must reject'},error='queue_full')
    client.call('cancel_message',{'message_id':prefix+'-p2'})
    client.call('cancel_message',{'message_id':prefix+'-visible'})
    for _ in range(15):
        status=client.device()
        if status['visible_message'] and status['visible_message']['message_id']==prefix+'-p1':break
        time.sleep(.2)
    else:raise AssertionError(status)
    print('FIFO, priority, capacity, duplicate and cancellation: PASS',flush=True)
    client.call('set_state',{'state':'on_air','lease_seconds':2,'valid_for':3})
    time.sleep(5)
    status=client.device()
    assert status['displayed_state']=='unknown',status
    assert status['visible_message']['message_id']==prefix+'-p1',status
    assert status['pending']==[prefix+'-p3'],status
    print('Freshness expiry and UNKNOWN message retention: PASS',flush=True)
    for name in ('p1','p3'):
        client.call('cancel_message',{'message_id':prefix+'-'+name})
    client.call('set_state',{'state':'camera_active','lease_seconds':15,'valid_for':60})
    client.call('show_message',{'title':'ANIMATION PAUSED','body':'The sign holds still while this card is visible. It closes after 12 seconds.','duration':12})
    print('VISUAL CHECK: static sign behind message for 12 seconds',flush=True)
    time.sleep(15)
    status=client.device();assert status['visible_message'] is None,status
    print('Message expired; ambient animation resumes: PASS',flush=True)


if __name__=='__main__':main()
