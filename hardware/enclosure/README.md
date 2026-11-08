# Display enclosure for a 15-series strut

Open `display_case.scad` in OpenSCAD. The default assembly shows the installed front with the 14-pin header on the right and the Pico's micro-USB port pointing down. Choose **exploded** to see the halves or **section** to cut through both mounting posts. The display, Pico, fasteners and rail in those views are simplified references.

The two production STLs are **faceplate** and **rear_shell**. Two visible ¼″ bolts pass through the faceplate ears, through matching shoulders in the shell, and into T-nuts in the same horizontal slot. The shoulders carry bolt load. Four small seats capture the display PCB at its corners and two pins locate it. The front lip clears the touch glass.

| Default geometry | Dimension |
| --- | --- |
| Body excluding mounting ears | 113.34 × 67.04 mm |
| Overall including ears, excluding bolt heads | 145.74 × 67.04 × 19.20 mm |
| Bolt spacing and height | 127.34 mm apart, 19.05 mm below the top |
| Bolt through-hole / front head recess | 6.9 mm / 13.2 mm |
| Screen opening at its narrowest | 84.32 × 56.48 mm around the 83.52 × 55.68 mm active area |
| Screen opening center, relative to PCB center in front view | 2.85 mm left, 0.03 mm up |
| Plastic around the PCB | 2.2 mm walls and 0.45 mm clearance per side |

The display geometry comes from the [module drawing](../4.0inch_SPI_Size.webp), rotated to match the [installation photo](../20261105_215012.jpg). The mount uses the [38.10 mm extrusion drawing](../t%20strut.jpg). The Pico cradle uses the 11.4 × 47 mm hole pattern and 1.3 mm nominal socket overhang from figure 3 of the [Raspberry Pi Pico 2 W datasheet](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf).

## Fit samples and hardware

Measure each bolt from the **underside of its flat head to the tip**. Choose a matching pair of ¼″-20 internal-drive bolts and matching 15-series T-nuts. The recess is Ø13.2 mm; check the head and drive tool fit. The default model uses ½″ bolts. Choose the faceplate by bolt length; both versions use the same rear shell. The Pico pushes onto two tapered pins.

| Bolt length | Faceplate STL | Grip (head seat to rail) | Bolt past rail face |
| --- | --- | --- | --- |
| ½″ (12.70 mm) | `faceplate.stl` | 5.30 mm | 7.40 mm |
| ⅝″ (15.875 mm) | `faceplate_5_8.stl` | 8.475 mm | 7.40 mm |
| ¾″ (19.05 mm) | `faceplate_3_4.stl` | 11.65 mm | 7.40 mm |

The recesses are different depths, so use the same bolt length at both ends. Dimensions assume no washer. The front post seats against a 2.4 mm flange in the rear ear. In the rail reference, the threaded nut starts 3.05 mm behind the rail face; actual nut position and slot depth determine the usable engagement.

- Print **fit_front**, **fit_front_5_8** or **fit_front_3_4** for your bolt length, plus **fit_rear**. Nest the post, fit the pair on the rail with the actual T-nut, and snug the bolt. The head should bear flat, both pieces should clamp against the rail, and the tip should clear the slot floor. The paper template checks hole spacing; use the printed ear to check bolt reach.
- Print **fit_usb** to check the two USB-end Pico supports, connector position, and your plug overmold. The socket mouth aligns with the bottom edge of the display PCB, 2.65 mm inboard of the enclosure edge. A 15 mm wide notch runs through the bottom wall and back panel to 0.4 mm past the socket mouth. Check that your plug seats fully with the boards in their wired position.
- Use the full faceplate as the screen fit test. Lay it face down, lower the display onto the corner seats, and check the aperture at all four lit edges.

The [side photo](../20261107_153330.jpg) shows a ruler in 32nds of an inch. The USB socket mouth lines up roughly with the 12/32 to 16/32 marks, about 9.5–12.7 mm above the tabletop with the display face down. The model places the Pico component-side PCB plane 9.5 mm from the glass face and the top of the socket at about 12.4 mm. The inside rear wall is 14.5 mm from the glass, leaving about 2.1 mm beyond the modeled socket. The taller-looking wire loops farther behind the ruler have an uncertain height because of perspective. Check that they clear the rear wall when the shell seats.

The faceplate assumes glass 3.1 mm above the display PCB, a 1.6 mm PCB and 0.5 mm air above the glass. In the OpenSCAD Customizer, adjust `cavity_from_glass` for wire clearance, `pico_from_glass` for the Pico support height and `usb_from_right` (39 mm from the [rear photo](../20261107_153244.jpg)) for the socket centerline. The two pins taper from 1.9 mm to 1.2 mm to guide the board into place. Check the USB-end pin on **fit_usb** and reduce `pico_pin_diameter` if your print binds. Recheck bolt length after changing the depth.

## Print and assemble

The STLs sit on the print bed in their intended orientation, faceplate cosmetic face down and shell rail face down. A starting point for FDM is PETG, a 0.4 mm nozzle, 0.2 mm layers and four walls. Inspect the slice near the mounting ears and locating pins. The open USB notch prints without supports. Check the underside of the flat bolt seats in the slicer; use removable supports inside the head recesses if the ear sample sags.

1. Place the faceplate face down on a clean surface. Lower the display into it with the header on the right **as seen from the front**. Seat the PCB on the corner pads. Check for clearance above the glass and around both header rows.
2. With the Pico component side toward the rear shell, align its two diagonal mounting holes with the tapered pins. Push the board gently down onto the four pads and check that the USB socket lines up with the bottom opening.
3. Arrange the wire loops, then mate the shells by hand. Both ear shoulders should meet easily. Adjust the depth if the wires press on the cover. The small hole in the rear gives access to BOOTSEL below the rail.
4. Set the T-nuts in the horizontal slot, offer up the enclosure, and start both front bolts. Snug them evenly by hand. Check cable clearance beside the vertical upright before tightening. Secure the cable to the rig with slack at the plug. Check touch response including the four edges after mounting.

## Rebuild and check the default exports

Run from the repository root. Set `scad` to your OpenSCAD executable.

```sh
scad=/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD
mkdir -p build/enclosure
for part in faceplate rear_shell fit_front fit_rear fit_usb; do
    "$scad" --hardwarnings --export-format binstl -D "part=\"$part\"" \
        -o "build/enclosure/$part.stl" hardware/enclosure/display_case.scad || exit 1
done
for part in faceplate fit_front; do
    "$scad" --hardwarnings --export-format binstl -D 'mount_bolt_length=15.875' -D "part=\"$part\"" \
        -o "build/enclosure/${part}_5_8.stl" hardware/enclosure/display_case.scad || exit 1
    "$scad" --hardwarnings --export-format binstl -D 'mount_bolt_length=19.05' -D "part=\"$part\"" \
        -o "build/enclosure/${part}_3_4.stl" hardware/enclosure/display_case.scad || exit 1
done
.venv/bin/python -m unittest hardware.enclosure.test_exports -v
```

The export checks verify the default geometry. Repeat the physical fit checks for your printer and hardware.
