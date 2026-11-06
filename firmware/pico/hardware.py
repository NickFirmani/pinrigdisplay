"""Pico 2 W SPI display/touch; one loop owns both devices, CS always explicit."""
from pixels import decode
import framebuf
import gc
import json
import math
import struct
import io
import time
from machine import Pin, SPI


class Hardware:
    def __init__(self):
        self.lcd_cs=Pin(17,Pin.OUT,value=1)
        self.touch_cs=Pin(22,Pin.OUT,value=1)
        self.dc=Pin(20,Pin.OUT,value=0)
        self.reset=Pin(21,Pin.OUT,value=1)
        self.irq=Pin(15,Pin.IN)
        self.spi=SPI(0,baudrate=20_000_000,polarity=0,phase=0,sck=Pin(18),mosi=Pin(19),miso=Pin(16))
        self.chunk=bytearray(15360)
        self.card_buffer=bytearray(480*132*2)
        self.card=framebuf.FrameBuffer(self.card_buffer,480,132,framebuf.RGB565)
        self.palette=framebuf.FrameBuffer(bytearray(4),2,1,framebuf.RGB565)
        self.palette.pixel(0,0,0)
        self.palette.pixel(1,0,self.color(245,241,232))
        with open('assets/fonts.json') as f:self.metrics=json.load(f)
        self.fonts={}
        for size in (22,24):
            with open('assets/font%d.bin'%size,'rb') as f:self.fonts[size]=bytearray(f.read())
        self.motion_phase=None
        self.bytes_written=0
        self.motion_seconds=0
        self.signature=None
        self.card_signature=None
        self.initialize()

    @staticmethod
    def color(r,g,b):
        value=((r&248)<<8)|((g&252)<<3)|(b>>3)
        return ((value&255)<<8)|(value>>8)

    def command(self, cmd, data=b''):
        self.lcd_cs(0)
        try:
            self.dc(0);self.spi.write(bytes([cmd]))
            if data:self.dc(1);self.spi.write(data)
        finally:self.lcd_cs(1)

    def initialize(self):
        self.touch_cs(1);self.lcd_cs(1)
        self.reset(1);time.sleep_ms(10);self.reset(0);time.sleep_ms(120);self.reset(1);time.sleep_ms(200)
        self.command(1);time.sleep_ms(150);self.command(0x11);time.sleep_ms(120)
        for cmd,data in ((0xF0,b'\xc3'),(0xF0,b'\x96'),(0x36,b'\x28'),(0x3A,b'\x55'),
            (0xB4,b'\x01'),(0xB7,b'\xc6'),(0xC0,b'\x80\x45'),(0xC1,b'\x13'),
            (0xC2,b'\xa7'),(0xC5,b'\x0a'),(0xE8,b'\x40\x8a\x00\x00\x29\x19\xa5\x33'),
            (0xE0,b'\xf0\x06\x0b\x07\x06\x05\x2e\x33\x47\x3a\x17\x16\x2e\x31'),
            (0xE1,b'\xf0\x09\x0d\x09\x08\x23\x2e\x33\x46\x38\x13\x13\x2c\x32'),
            (0xF0,b'\x3c'),(0xF0,b'\x69'),(0x20,b''),(0x13,b''),(0x29,b'')):
            self.command(cmd,data)
        time.sleep_ms(100)

    def window(self,x,y,w,h):
        x1,y1=x+w-1,y+h-1
        self.command(0x2A,bytes([x>>8,x&255,x1>>8,x1&255]))
        self.command(0x2B,bytes([y>>8,y&255,y1>>8,y1&255]))
        self.command(0x2C)

    def image(self,path):
        self.spi.init(baudrate=20_000_000)
        self.touch_cs(1)
        self.window(0,0,480,320)
        self.lcd_cs(0);self.dc(1)
        try:
            with open(path,'rb') as source:
                total=0
                while True:
                    header=source.read(2)
                    if not header:break
                    if len(header)!=2:raise OSError('invalid image header')
                    size=header[0]|(header[1]<<8)
                    if size>30724:raise OSError('image block too large')
                    block=source.read(size)
                    if len(block)!=size:raise OSError('truncated image')
                    count=decode(block,self.chunk,size,len(self.chunk))
                    if count<=0:raise OSError('invalid image block')
                    self.spi.write(memoryview(self.chunk)[:count]);total+=count
                    self.bytes_written+=count
                if total!=307200:raise OSError('invalid image size')
        finally:self.lcd_cs(1)

    def glyph(self,char,size):
        return self.metrics[str(size)].get(str(ord(char)),self.metrics[str(size)]['9633'])

    def lines(self,text,size,max_lines):
        lines=['']
        widths=[0]
        for char in text.replace('\t','    '):
            width=self.glyph(char,size)[1] if char!='\n' else 0
            if char=='\n' or widths[-1]+width>452:
                if len(lines)==max_lines:
                    ell=self.glyph('…',size)[1]
                    while lines[-1] and widths[-1]+ell>452:
                        widths[-1]-=self.glyph(lines[-1][-1],size)[1]
                        lines[-1]=lines[-1][:-1]
                    lines[-1]+='…'
                    break
                lines.append('');widths.append(0)
            if char!='\n':lines[-1]+=char;widths[-1]+=width
        return lines

    def text(self,text,x,y,size):
        source=memoryview(self.fonts[size])
        for char in text:
            offset,width,stride,length=self.glyph(char,size)
            glyph=framebuf.FrameBuffer(source[offset:offset+length],stride,28,framebuf.MONO_HLSB)
            self.card.blit(glyph,x,y,0,self.palette)
            x+=width

    def make_card(self,msg,fault):
        signature=(msg['id'] if msg else None,fault)
        if signature==self.card_signature:return
        self.card.fill(self.color(13,28,49))
        self.card.hline(12,1,456,self.color(116,162,155))
        if msg:
            p=msg['params']
            title=('TAP TO ACK: ' if p['requires_ack'] else '')+p['title']
            body=p['body']
            if fault:title='TOUCH ACK FAILED';body=fault+'; message retained'
            for line in self.lines(title,24,1):self.text(line,14,10,24)
            y=45
            for line in self.lines(body,22,3):self.text(line,14,y,22);y+=26
        self.card_signature=signature

    def render(self,state,msg,height,phase,fault):
        step=max(0,min(3,round((height-188)/44)))
        period={'on_air':4,'camera_active':3,'camera_inactive':6}.get(state,6)
        level=round((1-math.cos(phase*2*math.pi/period)))
        if step==3 or state=='unknown':level=0
        signature=(state,step,level,msg['id'] if msg else None,fault)
        if signature==self.signature:
            if state!='unknown' and step==3:self.animate_on_air(phase,state)
            return
        gc.collect()
        try:
            self.image('assets/%s-%d-%d.r'%(state,step,level))
            h=188+44*step
            if h<320:
                self.make_card(msg,fault)
                self.window(0,h,480,320-h)
                self.lcd_cs(0);self.dc(1)
                try:self.spi.write(memoryview(self.card_buffer)[:480*(320-h)*2])
                finally:self.lcd_cs(1)
            self.signature=signature
            self.motion_phase=0 if state!='unknown' and step==3 else None
            if state!='unknown' and step==3:self.animate_on_air(phase,state)
        except Exception:
            self.signature=None
            raise

    def animate_on_air(self, phase, state='on_air'):
        """Apply grouped barberpole patches; a failed phase forces a full repaint."""
        target=int(phase/.750)%4
        if target==self.motion_phase:return
        started=time.ticks_ms()
        self.spi.init(baudrate=20_000_000)
        self.touch_cs(1)
        try:
            if getattr(self,'motion_asset_state',None)!=state:
                self.motion_assets=None
                gc.collect()
                assets=[]
                for index in range(4):
                    with open('assets/%s-motion-%d.bin'%(state,index),'rb') as source:
                        assets.append(source.read())
                self.motion_assets=assets
                self.motion_asset_state=state
            with io.BytesIO(self.motion_assets[target]) as source:
                if source.read(4)!=b'PDM2':raise OSError('invalid motion asset')
                while True:
                    header=source.read(8)
                    if not header:break
                    if len(header)!=8:raise OSError('truncated motion header')
                    x,y,w,h=struct.unpack('<4H',header)
                    size=w*h*2
                    if not w or not h or x+w>480 or y+h>320 or size>len(self.chunk):
                        raise OSError('invalid motion rectangle')
                    packed_size=source.read(2)
                    if len(packed_size)!=2:raise OSError('truncated motion size')
                    packed_size=struct.unpack('<H',packed_size)[0]
                    if packed_size>30724:raise OSError('motion block too large')
                    data=source.read(packed_size)
                    if len(data)!=packed_size:raise OSError('truncated motion pixels')
                    if decode(data,self.chunk,len(data),len(self.chunk))!=size:
                        raise OSError('invalid motion block')
                    data=memoryview(self.chunk)[:size]
                    self.window(x,y,w,h)
                    self.lcd_cs(0);self.dc(1)
                    try:self.spi.write(data)
                    finally:self.lcd_cs(1)
                    self.bytes_written+=size
            self.motion_phase=target
            self.motion_seconds=time.ticks_diff(time.ticks_ms(),started)/1000
        except Exception:
            self.signature=None
            self.motion_phase=None
            raise

    def pressed(self):
        self.lcd_cs(1)
        if self.irq():return False
        self.spi.init(baudrate=100_000)
        def read(cmd):
            self.touch_cs(0)
            try:
                result=bytearray(3)
                self.spi.write_readinto(bytes([cmd,0,0]),result)
                return ((result[1]<<8)|result[2])>>3
            finally:self.touch_cs(1)
        z1,z2=read(0xB0),read(0xC0)
        return 100<z1<4095 and 0<z2<4000
