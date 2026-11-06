"""Build Pico flash assets from the existing Pillow renderer and fonts."""
import argparse
import json
from pathlib import Path
import sys
import struct
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from pinrig_artwork.pages import PageRenderer, _font
from pinrig_artwork.renderer import encode_rgb565


def pack_block(raw):
    """Encode exact RGB565 bytes with bounded run/literal records."""
    pixels=[raw[i:i+2] for i in range(0,len(raw),2)]
    output=bytearray();literal=[]
    def flush():
        if literal:
            output.extend(struct.pack('<H',len(literal)))
            output.extend(b''.join(literal));literal.clear()
    i=0
    while i<len(pixels):
        end=i+1
        while end<len(pixels) and pixels[end]==pixels[i]:end+=1
        count=end-i
        if count>=3:
            flush();output.extend(struct.pack('<H',32768|count));output.extend(pixels[i])
        else:literal.extend(pixels[i:end])
        i=end
    flush()
    return bytes(output)


def pack_image(raw):
    output=bytearray()
    for offset in range(0,len(raw),15360):
        block=pack_block(raw[offset:offset+15360])
        output.extend(struct.pack('<H',len(block)));output.extend(block)
    return output


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    pages = PageRenderer()
    for state in ('on_air','camera_active','camera_inactive','unknown'):
        for level in range(3 if state!='unknown' else 1):
            if state=='unknown': sign=pages.unknown_status()
            elif state=='on_air': sign=pages.on_air(.78+.11*level)
            else: sign=pages.camera_status(active=state=='camera_active',level=.78+.11*level)
            for step in range(4):
                height=188+44*step
                image=Image.new('RGB',(480,320),'#070f20')
                scaled=sign.copy();scaled.thumbnail((480,height),Image.Resampling.LANCZOS)
                image.paste(scaled,((480-scaled.width)//2,(height-scaled.height)//2))
                raw=encode_rgb565(image).pixels
                (output/f'{state}-{step}-{level}.r').write_bytes(pack_image(raw))
    # Fixed-height proportional glyphs in MONO_HLSB format for framebuf.blit.
    metrics={}
    for size in (22,24):
        font=_font(size,bold=size==24)
        offsets={};data=bytearray()
        for code in list(range(32,127))+[0x2026,0x25a1]:
            char=chr(code)
            width=max(1,round(font.getlength(char)))
            stride=(width+7)//8*8
            image=Image.new('1',(stride,28))
            ImageDraw.Draw(image).text((0,0),char,font=font,fill=1)
            packed=bytearray(stride//8*28)
            for y in range(28):
                for x in range(width):
                    if image.getpixel((x,y)):packed[y*(stride//8)+x//8]|=1<<(7-x%8)
            offsets[str(code)]=[len(data),width,stride,len(packed)]
            data.extend(packed)
        (output/f'font{size}.bin').write_bytes(data)
        metrics[str(size)]=offsets
    (output/'fonts.json').write_text(json.dumps(metrics,separators=(',',':')))
    total=sum(p.stat().st_size for p in output.iterdir())
    print('Asset bytes:',total)
    if total>2_000_000:raise RuntimeError('asset budget exceeded')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
