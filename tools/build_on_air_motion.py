"""Build full-size ON AIR phases and exact dirty runs, excluding steady pixels."""
import struct
from pathlib import Path
from pinrig_artwork.pages import PageRenderer
from pinrig_artwork.renderer import encode_rgb565
from tools.build_pico_assets import pack_image, pack_block


def dirty_rectangles(frames, width=480, height=320):
    """Merge identical changing row spans vertically; safe for skipped phases."""
    active={}
    result=[]
    for y in range(height):
        spans=[]
        x=0
        while x<width:
            offset=(y*width+x)*2
            if all(f[offset:offset+2]==frames[0][offset:offset+2] for f in frames[1:]):
                x+=1
                continue
            start=x
            while x<width:
                offset=(y*width+x)*2
                if all(f[offset:offset+2]==frames[0][offset:offset+2] for f in frames[1:]):break
                x+=1
            spans.append((start,x-start))
        next_active={}
        for span in spans:
            x,w=span
            old=active.pop(span,None)
            next_active[span]=(x,old[1],w,old[3]+1) if old else (x,y,w,1)
        result.extend(active.values())
        active=next_active
    return result+list(active.values())


def breathing_frames():
    """Five subtle background levels; trim and text drawing stay fixed."""
    levels=(.76,.772,.80,.828,.84)
    return [encode_rgb565(PageRenderer().on_air(.78,background_level=level)).pixels
            for level in levels]


def grouped_rectangles(frames, tile=10):
    """Group changed pixels into tiles to trade a few bytes for fewer windows."""
    dirty=dirty_rectangles(frames)
    cells=set()
    for x,y,w,h in dirty:
        for ty in range(y//tile,(y+h-1)//tile+1):
            for tx in range(x//tile,(x+w-1)//tile+1):
                cells.add((tx,ty))
    rects=[]
    for ty in sorted({ty for tx,ty in cells}):
        columns=sorted(tx for tx,row in cells if row==ty)
        start=previous=columns[0]
        for tx in columns[1:]+[1000]:
            if tx!=previous+1:
                x=start*tile;y=ty*tile
                rects.append((x,y,min(480-x,(previous-start+1)*tile),min(tile,320-y)))
                start=tx
            previous=tx
    return rects


STATES = ('on_air', 'camera_active', 'camera_inactive')


def motion_frames(state):
    """Render matching phase-zero artwork and four full-size stripe phases."""
    if state not in STATES:
        raise ValueError('unsupported animated state')
    pages=PageRenderer()
    return [encode_rgb565(pages.on_air(.78,p) if state=='on_air' else
            pages.camera_status(active=state=='camera_active',level=.78,stripe_phase=p)).pixels
            for p in range(4)]


def build(output: Path):
    for state in STATES:
        build_state(output,state)


def build_state(output: Path, state):
    output.mkdir(parents=True,exist_ok=True)
    frames=motion_frames(state)
    # Contiguous bands trade redundant steady pixels for far fewer windows.
    rects=grouped_rectangles(frames)
    (output/(state+'-3-0.r')).write_bytes(pack_image(frames[0]))
    for phase,frame in enumerate(frames):
        data=bytearray(b'PDM2')
        for x,y,w,h in rects:
            data.extend(struct.pack('<4H',x,y,w,h))
            pixels=bytearray()
            for row in range(y,y+h):
                start=(row*480+x)*2
                pixels.extend(frame[start:start+w*2])
            block=pack_block(pixels)
            data.extend(struct.pack('<H',len(block)))
            data.extend(block)
        (output/('%s-motion-%d.bin'%(state,phase))).write_bytes(data)
    print(state,'rectangles:',len(rects),'pixel bytes/phase:',sum(w*h*2 for x,y,w,h in rects))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
