"""MicroPython device state machine. Hardware and clocks are injected."""
import json
from commands import Command, CommandError, response, error_response

RETRY_SECONDS = 15
RETRY_CAPACITY = 64


class Device:
    def __init__(self, display, store, clock, session, new_id):
        self.display, self.store, self.clock = display, store, clock
        self.session, self.new_id = session, new_id
        self.state = 'unknown'
        self.displayed = None
        self.revision = 0
        self.displayed_revision = 0
        self.diagnostic = 'Waiting for current state'
        self.deadline = None
        self.visible = None
        self.pending = []
        self.history = []
        self.cache = []
        self.fault = None
        self.touch_fault = None
        self.touch_available = True
        self.released = False
        self.gesture = None
        self.height = self.start_height = self.target = 320
        self.layout_at = clock()
        self.phase = 0.
        self.previous_at = self.layout_at
        self.was_moving = False
        self.last_signature = None
        self.last_render_seconds = 0.
        self.closed = False

    def geometry(self, now):
        return self.target

    def layout(self, now):
        target = 188 if self.visible else 320
        if target != self.target:
            self.gesture = None
            self.target = target

    def finish(self, msg, outcome):
        self.gesture = None
        self.history.append((msg['id'], outcome))
        self.history = self.history[-16:]

    def next_message(self, now):
        if self.visible is None and self.pending:
            # MicroPython sorting is not stable: use an explicit arrival sequence.
            self.pending.sort(key=lambda m: (-m['params']['priority'], m['order']))
            self.visible = self.pending.pop(0)
        self.layout(now)

    def advance(self, now):
        if self.deadline is not None and now >= self.deadline:
            self.deadline = None
            self.state = 'unknown'
            self.diagnostic = 'Host command lease expired'
            self.revision += 1
            self.layout(now)
        if self.visible and self.visible['expires'] is not None and now >= self.visible['expires']:
            self.finish(self.visible, 'expired')
            self.visible = None
            self.next_message(now)

    def handle(self, value):
        rid = value.get('request_id') if isinstance(value, dict) else None
        if not isinstance(rid, str) or len(rid)>64:
            rid = None
        try:
            cmd = Command.parse(value)
            now = self.clock()
            self.advance(now)
            if cmd.operation == 'hello':
                return response(rid, {'session':self.session, 'retry_seconds':RETRY_SECONDS,
                    'retry_capacity':RETRY_CAPACITY, 'max_pending':3,
                    'acknowledgment_available':self.touch_available, 'platform':'pico2w'})
            if cmd.operation == 'status':
                return response(rid, self.status())
            if cmd.session != self.session:
                raise CommandError('session_changed', 'new handshake required; never replay old messages')
            self.cache = [e for e in self.cache if now < e[3]]
            for old_id, old, reply, _ in self.cache:
                if old_id == rid:
                    if old != cmd.to_dict():
                        raise CommandError('request_conflict', 'request ID reused with different content')
                    return json.loads(reply)
            if len(self.cache)>=RETRY_CAPACITY:
                raise CommandError('retry_capacity', 'retry window full')
            try:
                result = self.apply(cmd, now)
                self.render(now)
                reply = response(rid, dict(result, accepted=True,
                    display_success=self.fault is None, display_fault=self.fault))
            except CommandError as error:
                reply = error_response(rid, error.code, str(error))
            self.cache.append((rid, cmd.to_dict(), json.dumps(reply), now+RETRY_SECONDS))
            return reply
        except CommandError as error:
            return error_response(rid, error.code, str(error))

    def apply(self, cmd, now):
        p = cmd.params
        if cmd.operation == 'set_state':
            self.state = p['state']
            self.diagnostic = p['diagnostic']
            self.deadline = now+min(p['lease_seconds'],p['valid_for'])
            self.revision += 1
            return {'revision':self.revision}
        if cmd.operation == 'show_message':
            if p['requires_ack'] and not self.touch_available:
                raise CommandError('ack_unavailable','touch is unavailable')
            if self.visible and p['priority']<=self.visible['params']['priority'] and len(self.pending)>=3:
                raise CommandError('queue_full','at most three pending messages')
            msg = {'id':cmd.request_id,'params':dict(p),'status':'opening','expires':None,'order':self.revision}
            if self.visible and p['priority']>self.visible['params']['priority']:
                self.finish(self.visible,'dropped')
                self.visible = None
            if self.visible is None:
                self.visible = msg
            else:
                self.pending.append(msg)
            self.revision += 1
            self.layout(now)
            return {'message_id':msg['id'],'text_policy':'verbatim; overflow ellipsis; unsupported glyphs shown as boxes'}
        if cmd.operation == 'cancel_message':
            mid = p['message_id']
            if self.visible and self.visible['id']==mid:
                self.finish(self.visible,'cancelled')
                self.visible = None
            else:
                found = next((m for m in self.pending if m['id']==mid),None)
                if found:
                    self.pending.remove(found)
                    self.finish(found,'cancelled')
                elif mid not in dict(self.history):
                    raise CommandError('not_found','unknown message')
            self.next_message(now)
            return {'message_id':mid,'status':dict(self.history)[mid]}
        if cmd.operation == 'confirm_interaction':
            try:
                self.store.confirm(p['interaction_id'])
            except Exception as error:
                raise CommandError('unavailable','cannot confirm: '+str(error))
            return {'interaction_id':p['interaction_id'],'confirmed':True}
        raise CommandError('invalid_request','unsupported operation')

    def render(self, now):
        height = self.geometry(now)
        moving = abs(height-self.target)>.01
        if not moving and not self.was_moving and self.visible is None:
            self.phase += max(0.,now-self.previous_at)
        self.previous_at, self.was_moving = now,moving
        self.height = height
        try:
            started = self.clock()
            self.display.render(self.state,self.visible,height,self.phase,self.touch_fault)
            self.last_render_seconds = self.clock()-started
            self.displayed = self.state
            self.displayed_revision = self.revision
            self.fault = None
            if self.visible and self.visible['status']=='opening' and not moving:
                self.visible['status']='visible'
                if not self.visible['params']['requires_ack']:
                    self.visible['expires']=self.clock()+self.visible['params']['duration']
        except Exception as error:
            self.fault = str(error)[:160]

    def tick(self):
        now = self.clock()
        self.advance(now)
        self.render(now)

    def touch(self, pressed):
        now = self.clock()
        self.advance(now)
        if not self.touch_available:
            return
        if pressed:
            self.gesture = (self.visible['id'] if self.released and self.visible and
                self.visible['status']=='visible' and abs(self.geometry(now)-self.target)<.01 and not self.fault else None)
            self.released = False
            return
        self.released = True
        target,self.gesture = self.gesture,None
        if not self.visible or target!=self.visible['id']:
            return
        kind = 'acknowledged' if self.visible['params']['requires_ack'] else 'dismissed'
        item = {'interaction_id':self.new_id(),'message_id':target,'session':self.session,'kind':kind}
        try:
            self.store.append(item)
        except Exception as error:
            self.touch_fault=str(error)[:120]
            self.render(now)
            return
        self.touch_fault=None
        self.finish(self.visible,kind)
        self.visible=None
        self.next_message(now)
        self.render(now)

    def status(self):
        try:
            interactions = self.store.pending()
        except Exception as error:
            interactions=[]
            self.touch_fault=str(error)[:120]
            self.touch_available=False
        return {'session':self.session,'requested_state':self.state,'displayed_state':self.displayed,
            'revision':self.revision,'displayed_revision':self.displayed_revision,
            'healthy':not self.closed and self.fault is None and self.displayed is not None,
            'display_fault':self.fault,'touch_fault':self.touch_fault,
            'diagnostic':self.diagnostic if self.state=='unknown' else None,
            'visible_message':({'message_id':self.visible['id'],'status':self.visible['status']} if self.visible else None),
            'pending':[m['id'] for m in self.pending],'queue_depth':len(self.pending),
            'recent_messages':dict(self.history),'acknowledgment_available':self.touch_available,
            'interactions':interactions,'last_render_seconds':self.last_render_seconds,
            'motion_seconds':getattr(self.display,'motion_seconds',None),
            'display_bytes_written':getattr(self.display,'bytes_written',None)}
