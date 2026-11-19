"""Check the printed second shell against the second display's PCB datums."""

from pathlib import Path
import unittest

from hardware.enclosure.test_exports import triangles, z_crossings


BUILD = Path(__file__).resolve().parents[2] / "build" / "enclosure_2"


class SecondDisplayFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rear = triangles(str(BUILD / "rear_shell"))
        cls.sample = triangles(str(BUILD / "fit_usb"))

    def test_push_in_cradle_registers_the_pico_pcb_edge(self):
        # The USB-side mounting holes are 2 mm inboard of BOTH aligned PCB ends.
        x = 108.04 / 2 - 28
        edge = -61.74 / 2
        for dx, dy, height in ((-5.7, 2, 8.75), (5.7, 2, 7.4),
                               (-5.7, 49, 7.4), (5.7, 49, 8.75)):
            meshes = [self.rear, self.sample] if dy == 2 else [self.rear]
            for mesh in meshes:
                self.assertEqual(z_crossings(mesh, x + dx, edge + dy), [0, height])
        self.assertEqual(z_crossings(self.rear, 9.32, -27.57), [0, 2.4])

    def test_rear_and_sample_clear_the_plug_to_the_socket(self):
        for mesh in (self.rear, self.sample):
            for x in (18.55, 26.02, 33.49):
                for y in (-33.48, -32.17, -30.50):
                    self.assertEqual(z_crossings(mesh, x, y), [])
            self.assertEqual(z_crossings(mesh, 26.02, -30.4), [0, 2.4])
            for x in (18.45, 33.59):
                self.assertEqual(z_crossings(mesh, x, -32.2), [0, 11.9])

    def test_bootsel_access_follows_the_new_board(self):
        self.assertEqual(z_crossings(self.rear, 22.52, -18.87), [])
        self.assertEqual(z_crossings(self.rear, 11.52, -17.57), [0, 2.4])
