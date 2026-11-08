"""Check the default print-oriented binary STL exports. Run from the enclosure guide."""

from __future__ import annotations

import struct
import unittest
from collections import Counter
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[2] / "build" / "enclosure"


def triangles(part: str):
    data = (OUTPUT / f"{part}.stl").read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError(f"Expected a binary STL for {part}")
    return [
        (row[3:6], row[6:9], row[9:12])
        for row in struct.iter_unpack("<12fH", data[84:])
    ]


def z_crossings(mesh, x: float, y: float) -> list[float]:
    """Intersect a vertical line with projected triangles to locate the plastic."""
    hits = set()
    for a, b, c in mesh:
        u, v = b[0] - a[0], b[1] - a[1]
        s, t = c[0] - a[0], c[1] - a[1]
        det = u * t - v * s
        if abs(det) < 1e-9:
            continue
        dx, dy = x - a[0], y - a[1]
        i, j = (dx * t - dy * s) / det, (u * dy - v * dx) / det
        if min(i, j, 1 - i - j) >= -1e-9:
            hits.add(round(a[2] + i * (b[2] - a[2]) + j * (c[2] - a[2]), 3))
    return sorted(hits)


class EnclosureExports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = {p: triangles(p) for p in
                     ("faceplate", "faceplate_5_8", "faceplate_3_4", "rear_shell", "fit_front", "fit_front_5_8", "fit_front_3_4", "fit_rear", "fit_usb")}

    def test_all_prints_are_closed_and_on_bed(self):
        for part, mesh in self.parts.items():
            with self.subTest(part=part):
                edges = Counter((a, b) for tri in mesh for a, b in zip(tri, tri[1:] + tri[:1]))
                self.assertTrue(all(a != b and n == 1 and edges[b, a] == 1
                                    for (a, b), n in edges.items()))
                self.assertAlmostEqual(min(p[2] for tri in mesh for p in tri), 0)

    def test_mounts_accept_both_bolts_and_clamp_on_the_shoulders(self):
        front, rear = self.parts["faceplate"], self.parts["rear_shell"]
        top = max(p[1] for tri in front for p in tri)
        y = top - 19.05
        for x in (-63.67, 63.67):
            for dx, dy in ((3.18, 0), (-3.18, 0), (0, 3.18), (0, -3.18)):
                self.assertEqual(z_crossings(front, -x-dx, y+dy), [])
                self.assertEqual(z_crossings(rear, x+dx, y+dy), [])
            # Both ear shoulders carry load across the seam at the outside rim.
            a = z_crossings(front, -x-8.6, y+0.1)
            b = z_crossings(rear, x+8.6, y+0.1)
            self.assertEqual(len(a), 2)
            self.assertEqual(len(b), 2)
            self.assertAlmostEqual(a[1] + b[1], 19.2, places=2)

    def test_short_bolts_bear_on_both_halves_and_reach_the_t_nut(self):
        y = 14.47
        for suffix, length in (("", 12.7), ("_5_8", 15.875), ("_3_4", 19.05)):
            for name, rear_name, xs in (("faceplate", "rear_shell", (-63.67, 63.67)),
                                        ("fit_front", "fit_rear", (63.67,))):
                front = self.parts[name + suffix]
                rear = self.parts[rear_name]
                for x in xs:
                    with self.subTest(part=name + suffix, x=x):
                        for r in (3.65, 6.45):  # under head and near rim of its pocket
                            seat, post_end = z_crossings(front, -(x+r), y+0.03)
                            back, flange = z_crossings(rear, x+r, y+0.03)
                            self.assertAlmostEqual(back, 0)
                            self.assertAlmostEqual(post_end + flange, 19.2, places=2)
                            grip = post_end - seat + flange
                            self.assertAlmostEqual(length - grip, 7.4, places=2)
                        self.assertEqual(z_crossings(front, -x, y), [])
                        self.assertEqual(z_crossings(rear, x, y), [])

    def test_entire_active_rectangle_is_exposed_in_installed_orientation(self):
        for x in (-44.61, 38.91):
            for y in (-27.81, 27.87):
                self.assertEqual(z_crossings(self.parts["faceplate"], -x, y), [])
        # Plastic borders each side of the opening.
        for x in (-46.5, 40.8):
            self.assertTrue(z_crossings(self.parts["faceplate"], -x, 0.25))

    def test_pico_pushes_onto_two_pins_above_a_closed_shell_floor(self):
        rear = self.parts["rear_shell"]
        for x, y in ((9.32, -27.57), (20.72, 19.43)):
            # The pin rises through the 1 mm PCB from a wider bearing pad.
            self.assertEqual(z_crossings(rear, x, y), [0, 8.75])
            self.assertEqual(z_crossings(rear, x, y + 1.45), [0, 7.4])
        for x in (2.82, 27.22):
            self.assertEqual(z_crossings(rear, x, -22.07), [0, 2.4])

    def test_socket_mouth_aligns_with_display_pcb_edge(self):
        # The front USB-end pin is 2 mm from the Pico edge, which itself is
        # 1.3 mm behind the metal mouth. Measure its center on both exports.
        display_edge_y = -61.74 / 2
        for part in ("rear_shell", "fit_usb"):
            with self.subTest(part=part):
                ys = [y for tri in self.parts[part] for _, y, z in tri
                      if y < display_edge_y + 5 and abs(z - 8.75) < 0.001]
                self.assertTrue(ys, "USB-end locating pin missing")
                mouth_y = (min(ys) + max(ys)) / 2 - 3.3
                self.assertAlmostEqual(mouth_y, display_edge_y, places=3)

    def test_cable_cutout_reaches_socket_through_back_panel(self):
        for part in ("rear_shell", "fit_usb"):
            with self.subTest(part=part):
                mesh = self.parts[part]
                for x in (7.55, 15.02, 22.49):
                    for y in (-33.48, -32.2, -30.50):
                        self.assertEqual(z_crossings(mesh, x, y), [])
                # Material on both sides and just inboard of the cable relief.
                for x in (7.45, 22.60):
                    self.assertEqual(z_crossings(mesh, x, -32.2), [0, 11.9])
                self.assertEqual(z_crossings(mesh, 15.02, -30.40), [0, 2.4])


if __name__ == "__main__":
    unittest.main()
