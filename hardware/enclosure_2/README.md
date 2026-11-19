# Display 2 enclosure

Open **display_case.scad** in this folder. It uses the same faceplate, 19.2 mm depth, rail mounting ears and measured screws as [display 1](../enclosure/README.md). Use this display's rear shell and USB fit sample. The SCAD entry point includes the neighboring enclosure source; keep the two source directories together.

Looking at the [rear assembly photo](wired-display.jpg), the wired header is on the right and the socket points up. The center of the socket is approximately **28 mm from the wired short edge** of the red PCB: the image shows about 390 pixels from socket center to edge across a board about 1,500 pixels wide (108.04 mm). This is 11 mm closer to the header than display 1. In the installed front view the socket points down. Adjust **usb_from_right** if the paper overlay shows a lateral offset.

Seat the Pico with the green board's USB-end edge aligned with the red display board edge. The metal socket then overhangs both PCBs by 1.3 mm and is about 1.35 mm inboard of the case exterior. The rear notch clears the plug. The four seats, two diagonal locating pins and BOOTSEL opening move with the Pico. Check that the wires clear the side wall by the header before tightening the ears. The Pico height and wire space use the first case's dimensions; the top-down photo gives only the in-plane location.

**Fit before printing the case.** Print page 2 of the display 2 paper template at 100% and check its scale marks. Orient the rear as in the photo, align the punched display corner holes, then check the Pico holes with its board edge aligned. Use the fold-up gauge to check wire height. Print **fit_usb.stl** to check plug insertion with the real cable. The two production STLs are already oriented for printing.

To rebuild from the project root:

```sh
scad=/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD
mkdir -p build/enclosure_2
for part in faceplate rear_shell fit_usb fit_front fit_rear; do
    "$scad" --hardwarnings --export-format binstl -D "part=\"$part\"" \
        -o "build/enclosure_2/$part.stl" hardware/enclosure_2/display_case.scad || exit 1
done
.venv/bin/python -m unittest hardware.enclosure_2.test_exports -v
```
