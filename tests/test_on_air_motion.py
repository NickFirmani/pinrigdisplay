"""Exact dirty-region reconstruction, including arbitrary phase jumps."""
import unittest
from tools.build_on_air_motion import dirty_rectangles
from pinrig_artwork.pages import PageRenderer
from pinrig_artwork.renderer import encode_rgb565


class MotionTests(unittest.TestCase):
    def test_all_phase_jumps_reconstruct_without_writing_steady_pixels(self):
        frames=[encode_rgb565(PageRenderer().on_air(.78,p)).pixels for p in range(4)]
        rects=dirty_rectangles(frames)
        self.assertLess(sum(w*h*2 for x,y,w,h in rects),20000)
        for original in frames:
            for target in frames:
                actual=bytearray(original)
                for x,y,w,h in rects:
                    for row in range(y,y+h):
                        start=(row*480+x)*2
                        actual[start:start+w*2]=target[start:start+w*2]
                self.assertEqual(actual,target)
        for x,y,w,h in rects:
            for row in range(y,y+h):
                for col in range(x,x+w):
                    i=(row*480+col)*2
                    self.assertTrue(any(f[i:i+2]!=frames[0][i:i+2] for f in frames[1:]))

    def test_hardware_holds_barberpole_phase(self):
        import importlib.util
        import io
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('motion_hardware',
            Path(__file__).resolve().parents[1]/'firmware/pico/hardware.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'pixels':SimpleNamespace(decode=None),
                'framebuf':SimpleNamespace(),'machine':SimpleNamespace(Pin=None,SPI=None)}):
            spec.loader.exec_module(module)
        hw=module.Hardware.__new__(module.Hardware)
        hw.motion_phase=0
        hw.spi=SimpleNamespace(init=lambda **kw:None)
        hw.touch_cs=lambda value:None
        with patch.object(module,'time',SimpleNamespace(ticks_ms=lambda:0,ticks_diff=lambda a,b:0)), \
                patch('builtins.open',side_effect=lambda *a:io.BytesIO(b'PDM2')) as assets:
            hw.animate_on_air(.749)
            self.assertEqual(assets.call_count,0)
            hw.animate_on_air(.750)
            self.assertEqual(hw.motion_phase,1)
            hw.animate_on_air(1.499)
            self.assertEqual(assets.call_count,4)
            hw.animate_on_air(2.999)
            self.assertEqual(hw.motion_phase,3)
            hw.motion_phase=0
            hw.animate_on_air(.750,'camera_active')
            self.assertEqual(hw.motion_asset_state,'camera_active')
            self.assertEqual(assets.call_count,8)

    def test_breathing_changes_only_inner_panel(self):
        from tools.build_on_air_motion import breathing_frames
        frames=breathing_frames()
        self.assertEqual(len(set(frames)),5)
        for frame in frames[1:]:
            for y in range(320):
                for x in range(480):
                    if 38 <= x < 442 and 58 <= y < 262:continue
                    i=(y*480+x)*2
                    self.assertEqual(frame[i:i+2],frames[0][i:i+2])

    def test_grouped_patches_reconstruct_every_phase_jump(self):
        from tools.build_on_air_motion import grouped_rectangles
        from tools.build_on_air_motion import motion_frames
        for state in ('on_air','camera_active','camera_inactive'):
            self.check_grouped_frames(motion_frames(state),grouped_rectangles)

    def check_grouped_frames(self,frames,grouped_rectangles):
        rects=grouped_rectangles(frames)
        self.assertLess(len(rects),100)
        self.assertTrue(all(w*h*2<=15360 for x,y,w,h in rects))
        for original in frames:
            for target in frames:
                actual=bytearray(original)
                for x,y,w,h in rects:
                    for row in range(y,y+h):
                        i=(row*480+x)*2
                        actual[i:i+w*2]=target[i:i+w*2]
                self.assertEqual(actual,target)

    def test_camera_stripes_match_on_air_luminance_contrast(self):
        from pinrig_artwork.pages import _luminance, _scale_color, _camera_stripe
        for level in (.78,.89,1.):
            reference=(_luminance(_scale_color((220,49,22),level))+.05)/(\
                _luminance(_scale_color((170,30,16),level))+.05)
            for color in ((185,120,18),(52,70,87)):
                face=_scale_color(color,level)
                stripe=_camera_stripe(face,level)
                contrast=(_luminance(face)+.05)/(_luminance(stripe)+.05)
                self.assertAlmostEqual(contrast,reference,delta=.025)
                self.assertTrue(all(s<f for s,f in zip(stripe,face)))
