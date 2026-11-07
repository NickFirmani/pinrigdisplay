"""Pico scheduler contract tests on CPython; no hardware, network or delays."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pinrig_protocol import commands
from tests.helpers import Clock, command

SPEC=importlib.util.spec_from_file_location('pico_core',Path(__file__).resolve().parents[1]/'firmware/pico/core.py')
CORE=importlib.util.module_from_spec(SPEC)
sys.modules['commands']=commands
SPEC.loader.exec_module(CORE)
sys.modules.pop('commands')


class Display:
    def __init__(self):self.fail=False;self.phases=[]
    def render(self,state,message,height,phase,fault):
        if self.fail:raise OSError('SPI failed')
        self.phases.append(phase)


class Store:
    def __init__(self):self.items=[];self.fail=False
    def pending(self):return list(self.items)
    def append(self,item):
        if self.fail:raise OSError('storage full')
        self.items.append(item)
    def confirm(self,mid):self.items=[i for i in self.items if i['interaction_id']!=mid]


class PicoTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.display=Display();self.store=Store()
        self.device=CORE.Device(self.display,self.store,self.clock,'boot',lambda:'interaction-1')
        self.device.tick()

    def send(self,op,rid='state',**params):return self.device.handle(command(op,rid,**params))
    def state(self):return self.send('set_state',state='camera_active',lease_seconds=60,valid_for=60)
    def msg(self,rid='msg',**params):return self.send('show_message',rid,title='Booth',body='Check camera',**params)

    def test_boot_handshake_and_messages_while_unknown(self):
        self.assertEqual(self.device.status()['displayed_state'],'unknown')
        hello=self.send('hello')['result'];self.assertEqual(hello['retry_capacity'],64)
        self.assertEqual(hello['retry_seconds'],15)
        self.assertTrue(self.msg()['ok'])

    def test_leases_preserve_pending_and_visible_and_allow_ack(self):
        self.state();self.msg(requires_ack=True);self.msg('other',requires_ack=True)
        self.clock.advance(61);self.device.tick()
        self.assertEqual(self.device.state,'unknown')
        self.assertEqual(self.device.status()['recent_messages'],{})
        self.assertEqual(self.device.visible['id'],'msg')
        self.assertEqual(self.device.status()['pending'],['other'])
        self.device.touch(False);self.device.touch(True);self.device.touch(False)
        self.assertEqual(self.device.status()['recent_messages']['msg'],'acknowledged')
        self.assertEqual(self.device.visible['id'],'other')
        self.assertEqual(self.send('cancel_message','clear',message_id='other')['result']['status'],'cancelled')

    def test_explicit_unknown_and_recovery_preserve_message(self):
        self.state();self.msg(requires_ack=True)
        self.clock.advance(.5);self.device.tick()
        self.send('set_state','lost',state='unknown')
        self.assertEqual(self.device.visible['id'],'msg')
        self.assertEqual(self.device.height,188)
        self.assertTrue(self.msg('new',requires_ack=True)['ok'])
        self.send('set_state','recovery',state='on_air')
        self.assertEqual(self.device.visible['id'],'msg')
        self.assertEqual(self.device.status()['pending'],['new'])

    def test_normal_host_and_authority_cadence_does_not_fill_retry_window(self):
        from pinrig_host.delivery import LocalDelivery
        from pinrig_host.service import Host
        from pinrig_producers.authority import Authority
        from pinrig_host.client import LocalClient
        host=Host(LocalDelivery(self.device),clock=self.clock)
        authority=Authority('rig1',LocalClient(host),clock=self.clock)
        # Five minutes includes source publication, host renewals and booth traffic.
        for second in range(300):
            authority.observe_obs(False,8);authority.observe_video(True)
            self.assertTrue(authority.publish()['ok'],second)
            if second%10==0:
                mid='booth-'+str(second)
                self.assertTrue(authority.message('Ready',mid)['ok'],second)
                self.assertTrue(authority.clear(mid)['ok'],second)
            for _ in range(2):
                self.clock.advance(.5);host.tick();self.device.tick()
                self.assertIsNone(host.fault,second)
        self.assertEqual(self.device.state,'camera_active')

    def test_duplicate_and_conflict(self):
        self.state();reply=self.msg(duration=2)
        self.clock.advance(.5);self.device.tick();expiry=self.device.visible['expires']
        self.assertEqual(self.msg(duration=2),reply)
        self.assertEqual(self.device.visible['expires'],expiry)
        self.assertEqual(self.msg(duration=3)['error']['code'],'request_conflict')

    def test_capacity_preemption_fifo(self):
        self.state();self.msg('a',priority=4)
        for mid,p in [('b',1),('c',2),('d',2)]:self.msg(mid,priority=p)
        self.assertEqual(self.msg('overflow')['error']['code'],'queue_full')
        self.msg('high',priority=8)
        self.assertEqual(self.device.status()['recent_messages']['a'],'dropped')
        self.send('cancel_message','cancel',message_id='high')
        self.assertEqual(self.device.visible['id'],'c')

    def test_timer_starts_after_successful_opening(self):
        self.state();self.display.fail=True;self.msg(duration=1)
        self.clock.advance(.5);self.device.tick()
        self.assertIsNone(self.device.visible['expires'])
        self.display.fail=False;self.device.tick()
        self.assertEqual(self.device.visible['expires'],1.5)
        self.clock.advance(1);self.device.tick();self.assertIsNone(self.device.visible)

    def test_ack_persists_and_confirmation_is_idempotent(self):
        self.state();self.msg(requires_ack=True)
        self.clock.advance(10);self.device.tick();self.assertIsNotNone(self.device.visible)
        self.device.touch(False);self.device.touch(True);self.device.touch(False)
        self.assertEqual(self.store.items[0]['kind'],'acknowledged')
        self.assertIsNone(self.device.visible)
        for rid in ('c1','c2'):
            self.assertTrue(self.send('confirm_interaction',rid,interaction_id='interaction-1')['ok'])
        self.assertEqual(self.store.items,[])

    def test_storage_failure_retains_message(self):
        self.state();self.msg(requires_ack=True);self.clock.advance(.5);self.device.tick()
        self.store.fail=True
        self.device.touch(False);self.device.touch(True);self.device.touch(False)
        self.assertIsNotNone(self.device.visible)
        self.assertEqual(self.device.touch_fault,'storage full')

    def test_stale_press_cannot_ack_replacement(self):
        self.state();self.msg('a',requires_ack=True);self.clock.advance(.5);self.device.tick()
        self.device.touch(False);self.device.touch(True)
        self.msg('b',priority=9,requires_ack=True);self.device.touch(False)
        self.assertEqual(self.device.visible['id'],'b');self.assertEqual(self.store.items,[])

    def test_wrong_session_rejected(self):
        value=command('set_state',state='on_air');value['session']='old'
        self.assertEqual(self.device.handle(value)['error']['code'],'session_changed')

    def test_full_retry_window_rejects_without_early_eviction(self):
        for i in range(64):self.send('set_state',str(i),state='on_air')
        self.assertEqual(self.send('set_state','full',state='on_air')['error']['code'],'retry_capacity')
        self.clock.advance(15)
        self.assertTrue(self.send('set_state','new',state='on_air')['ok'])

    def test_pulse_freezes_during_layout(self):
        self.state();self.clock.advance(1);self.device.tick();phase=self.display.phases[-1]
        self.msg()
        for duration in (.2,.3):
            self.clock.advance(duration);self.device.tick()
            self.assertEqual(self.display.phases[-1],phase)
        self.clock.advance(.1);self.device.tick()
        self.assertAlmostEqual(self.display.phases[-1],phase)

    def test_outbox_read_failure_disables_touch_but_preserves_sign(self):
        self.state()
        def fail():raise OSError('outbox unreadable')
        self.store.pending=fail
        status=self.device.status()
        self.assertTrue(status['healthy'])
        self.assertFalse(status['acknowledgment_available'])
        self.assertEqual(status['touch_fault'],'outbox unreadable')


    def test_message_holds_pulse_until_card_closes(self):
        self.state();self.clock.advance(1);self.device.tick()
        phase=self.display.phases[-1]
        self.msg(requires_ack=True)
        self.clock.advance(.5);self.device.tick()
        self.clock.advance(5);self.device.tick()
        self.assertEqual(self.display.phases[-1],phase)
        self.send('cancel_message','cancel',message_id='msg')
        self.clock.advance(.5);self.device.tick()
        self.assertAlmostEqual(self.display.phases[-1],phase+.5)
        self.clock.advance(.1);self.device.tick()
        self.assertAlmostEqual(self.display.phases[-1],phase+.6)


class AssetCodecTests(unittest.TestCase):
    def test_run_and_literal_blocks_round_trip_exactly(self):
        from tools.build_pico_assets import pack_block
        import struct
        cases=[b'\x12\x34'*7680,bytes(range(256))*60,
               b'\xab\xcd'*5+b'\x00\x01\x00\x02'+b'\xff\x00'*17]
        for raw in cases:
            data=pack_block(raw);decoded=bytearray();offset=0
            while offset<len(data):
                token=struct.unpack_from('<H',data,offset)[0];offset+=2
                count=token&32767
                self.assertGreater(count,0)
                if token&32768:
                    decoded.extend(data[offset:offset+2]*count);offset+=2
                else:
                    decoded.extend(data[offset:offset+count*2]);offset+=count*2
            self.assertEqual(bytes(decoded),raw)


class PicoLayoutTests(unittest.TestCase):
    def test_unknown_uses_compact_asset_and_draws_message_card(self):
        spec=importlib.util.spec_from_file_location('pico_hardware',
            Path(__file__).resolve().parents[1]/'firmware/pico/hardware.py')
        module=importlib.util.module_from_spec(spec)
        # Only the board libraries are replaced; execute the real render method.
        with patch.dict(sys.modules,{'pixels':SimpleNamespace(decode=None),
                'framebuf':SimpleNamespace(),'machine':SimpleNamespace(Pin=None,SPI=None)}):
            spec.loader.exec_module(module)
        hardware=module.Hardware.__new__(module.Hardware)
        images=[];windows=[];writes=[];cards=[]
        hardware.signature=None
        hardware.card_buffer=bytearray(480*132*2)
        hardware.spi=SimpleNamespace(write=lambda data:writes.append(len(data)))
        hardware.image=lambda path,height:images.append(path)
        hardware.window=lambda *args:windows.append(args)
        hardware.make_card=lambda msg,fault:cards.append(msg)
        hardware.lcd_cs=lambda value:None
        hardware.dc=lambda value:None
        msg={'id':'booth-unknown'}
        hardware.render('unknown',msg,188,10,None)
        self.assertEqual(images,['assets/unknown-0-0.r'])
        self.assertEqual(windows,[(0,188,480,132)])
        self.assertEqual(writes,[480*132*2])
        self.assertEqual(cards,[msg])
        hardware.render('unknown',None,320,20,None)
        self.assertEqual(images[-1],'assets/unknown-3-0.r')
        self.assertEqual(len(writes),1)
