// Second wired display. Dimensions are in mm, facing the installed screen.
include <../enclosure/display_case.scad>

/* [Export / preview] */
part = "assembly"; // [assembly, exploded, section, faceplate, rear_shell, fit_front, fit_rear, fit_usb]

/* [Second display] */
// Estimated from the photo, measured inward from the display PCB's wired edge.
usb_from_right = 28;
// Flush PCB ends at the USB end. The socket projects 1.3 mm beyond both boards.
// The shared rear notch still clears the entire wall to the display PCB edge.
/* [Hidden] */
pico_y0 = -pcb.y/2;
