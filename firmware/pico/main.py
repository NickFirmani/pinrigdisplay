"""USB JSON-lines runtime. No worker threads: SPI clients never interleave."""
import gc
import json
import machine
import os
import select
import sys
import time
import ubinascii
from core import Device
from hardware import Hardware
from storage import Outbox
from commands import error_response


class Clock:
    def __init__(self):self.last=time.ticks_ms();self.total=0
    def __call__(self):
        now=time.ticks_ms();self.total+=time.ticks_diff(now,self.last);self.last=now
        return self.total/1000


def new_id():return ubinascii.hexlify(os.urandom(16)).decode()


def run():
    hardware=Hardware()
    try:
        store=Outbox()
        storage_fault=None
    except Exception as error:
        storage_fault=str(error)[:120]
        class FailedOutbox:
            def pending(self):raise OSError('acknowledgment outbox unavailable')
            def append(self,item):raise OSError('acknowledgment outbox unavailable')
            def confirm(self,mid):raise OSError('acknowledgment outbox unavailable')
        store=FailedOutbox()
    device=Device(hardware,store,Clock(),new_id(),new_id)
    if storage_fault:
        device.touch_available=False
        device.touch_fault=storage_fault
    device.tick()
    poll=select.poll();poll.register(sys.stdin,select.POLLIN)
    buffer=bytearray();discard=False
    last_touch=None;count=0
    next_frame=time.ticks_ms()
    while True:
        # Bound serial input per loop so bad framing cannot starve lease/touch.
        for _ in range(1024):
            if not poll.poll(0):break
            char=sys.stdin.buffer.read(1)
            if not char:break
            if char==b'\n':
                if discard:reply=error_response(None,'invalid_frame','frame too large')
                else:
                    try:
                        value=json.loads(buffer.decode('utf-8'))
                        reply=device.handle(value)
                    except (ValueError,UnicodeError,RuntimeError) as error:
                        reply=error_response(None,'invalid_frame',str(error)[:120])
                buffer=bytearray();discard=False
                sys.stdout.write(json.dumps(reply)+'\n')
                gc.collect()
            elif not discard:
                buffer.extend(char)
                if len(buffer)>8192:buffer=bytearray();discard=True
        if device.touch_available:
            try:
                pressed=hardware.pressed()
                count=count+1 if pressed==last_touch else 1
                last_touch=pressed
                if count==2:device.touch(pressed)
            except Exception as error:
                device.touch_available=False;device.touch_fault=str(error)[:120]
        if time.ticks_diff(time.ticks_ms(),next_frame)>=0:
            device.tick()
            next_frame=time.ticks_add(time.ticks_ms(),30)
        time.sleep_ms(10)


run()
