// Pinrig display enclosure, mm. Viewed from the installed front: X right, Y up,
// face at Z=0, depth measured towards the rail (-Z). STL modes orient for print.
part = "assembly"; // [assembly, exploded, section, faceplate, rear_shell, fit_front, fit_rear, fit_usb]

/* [Fit adjustments] */
// Height of the glass face above the display PCB front. Measure on your module.
glass_height = 3.1;
glass_gap = 0.5;
pcb_thickness = 1.6;
pcb_edge_gap = 0.45;
pcb_endplay = 0.30;
// Photo reads about 12–13 mm at the USB shell; allow extra room for the wires.
cavity_from_glass = 14.5;
// Socket centerline to RIGHT edge of display PCB, from rear assembly photo.
usb_from_right = 39;
// Depth from display glass to Pico component-side PCB surface.
pico_from_glass = 9.5;
// Base diameter of the tapered slip-fit locators in the Pico's 2.1 mm holes.
pico_pin_diameter = 1.9;
// Plug overmold width; includes free space for insertion.
plug_opening_width = 15;
bolt_clearance = 6.9;
// Under-head length of the two 1/4-20 bolts. Dimensions in mm.
mount_bolt_length = 12.7; // [12.7:1/2 inch, 15.875:5/8 inch, 19.05:3/4 inch]

/* [Hidden] */
$fn = 72;
e = 0.02;
pcb = [108.04, 61.74];
active = [83.52, 55.68];
// Drawing rotated 180 degrees to put J2 on the installed right.
// Drawing's right/bottom margins become installed left/top margins.
screen_xy = [-pcb.x/2 + 6.54 + 2.87 + active.x/2,
              pcb.y/2 - (61.74 - 0.40 - 61.00 + 2.66) - active.y/2];
window = active + [0.8, 0.8];
wall = 2.2;
face = 1.8;
back = 2.4;
inside = pcb + [2*pcb_edge_gap, 2*pcb_edge_gap];
body = inside + [2*wall, 2*wall];
glass_d = face + glass_gap;
board_d = glass_d + glass_height;
seam = board_d + pcb_thickness + pcb_endplay;
floor_d = glass_d + cavity_from_glass;
depth = floor_d + back;
rail = 38.10;
bolt_y = body.y/2 - rail/2;
bolt_x = body.x/2 + 7;
ear_r = 9.2;
// The front post nests in the rear ear and bears directly on its back flange.
post_d = 15.8;
head_well_d = 13.2;
rail_reach = 7.4;
seat_d = depth + rail_reach - mount_bolt_length;
pico_x = pcb.x/2 - usb_from_right;
case_bottom = -body.y/2;
socket_overhang = 1.3;
socket_mouth_y = -pcb.y/2; // Align the metal mouth with the display PCB edge.
pico_y0 = socket_mouth_y + socket_overhang;
pico_d = glass_d + pico_from_glass;
boot_xy = [pico_x - 3.5, pico_y0 + 12]; // figure 3, verify on fitted board
assert(glass_gap > 0 && pcb_endplay > 0 && pcb_edge_gap > 0);
assert(pico_d - 1 > board_d + pcb_thickness,
       "The Pico underside must clear the display PCB.");
assert(pico_pin_diameter > 1.2 && pico_pin_diameter <= 2.1,
       "Choose a locating pin that fits the Pico's 2.1 mm holes.");
assert(floor_d > pico_d + 2.9, "Increase cavity_from_glass to clear the USB socket.");
assert(abs(pico_x) + 12 < pcb.x/2 - 6, "Pico must clear the corner supports.");
assert(bolt_clearance >= 6.35 && bolt_clearance < head_well_d - 2);
assert(seat_d > 0 && floor_d - seat_d >= 2.5,
       "Bolt length must leave a recessed seat and enough faceplate below the head.");
assert(plug_opening_width >= 9 && plug_opening_width < 27);

module slab(d1, d2) {
    translate([0,0,-d2]) linear_extrude(d2-d1) children();
}
module rounded(size, r) {
    offset(r=r) square(size - [2*r,2*r], center=true);
}
module bolts() {
    for (x=[-bolt_x,bolt_x]) translate([x,bolt_y]) children();
}
module corners() {
    for (i=[-1,1], j=[-1,1])
        translate([i*(pcb.x/2-3), j*(pcb.y/2-3.42)]) children();
}
module pico_holes() {
    for (x=[-5.7,5.7], y=[2,49])
        translate([pico_x+x,pico_y0+y]) children();
}
module outline() {
    union() {
        rounded(body, 3.5);
        for (s=[-1,1]) hull() {
            translate([s*bolt_x,bolt_y]) circle(r=ear_r);
            translate([s*(body.x/2-5),bolt_y]) circle(r=ear_r+3);
        }
    }
}
module rims(d1,d2) {
    slab(d1,d2) difference() {
        outline();
        rounded(inside, 0.7);
    }
}
module screen_cut() {
    translate(screen_xy) hull() {
        slab(-e,0) square(window+[1.6,1.6],center=true);
        slab(0.8,face+e) square(window,center=true);
    }
}
module faceplate() {
    difference() {
        union() {
            difference() {
                slab(0,face) outline();
                screen_cut();
            }
            rims(face-e,seam);
            // Four corner seats take the board load. Two loose diagonal pins locate it.
            corners() slab(face-e,board_d) circle(d=5.0);
            for (s=[-1,1])
                translate([s*(pcb.x/2-3),s*(pcb.y/2-3.42)])
                    slab(board_d-e, board_d+min(1.1,pcb_thickness)) circle(d=2.5);
            bolts() slab(seam-e,floor_d) circle(d=post_d);
        }
        bolts() slab(-e,seat_d) circle(d=head_well_d);
        bolts() slab(seat_d-e,floor_d+e) circle(d=bolt_clearance);
    }
}
module rear_shell() {
    difference() {
        union() {
            slab(floor_d,depth) outline();
            rims(seam,floor_d+e);
            corners() slab(seam,floor_d+e) circle(d=5);
            // The Pico pushes onto two tapered locators and rests on four pads.
            pico_holes() slab(pico_d,floor_d+e) circle(d=4.2);
            for (i=[0,1]) translate([pico_x+(i-0.5)*11.4,pico_y0+2+i*47])
                translate([0,0,-pico_d-e])
                    cylinder(h=1.35+e,d1=pico_pin_diameter,d2=1.2);
        }
        bolts() slab(seam-e,depth+e) circle(d=bolt_clearance);
        bolts() slab(seam-e,floor_d) circle(d=post_d+0.6);
        // Open the bottom wall and back panel just past the socket mouth
        // so the plug shoulder can reach the recessed connector.
        translate([pico_x-plug_opening_width/2,case_bottom-e,-depth-e])
            cube([plug_opening_width,socket_mouth_y-case_bottom+0.4+e,depth-seam+2*e]);
        // Relieve the inboard faces of the two USB-end bosses around the metal can.
        translate([pico_x-4.35,pico_y0-1.4,-pico_d-3.5])
            cube([8.7,7,3.5+e]);
        translate(boot_xy) slab(floor_d-e,depth+e) circle(d=5);
    }
}
// Both coupon modes crop the same portion of the production geometry.
module ear_sample() {
    intersection() {
        children();
        translate([bolt_x-15,bolt_y-ear_r-3,-depth-e])
            cube([26,2*ear_r+6,depth+2*e]);
    }
}
module reference_display() {
    color("#9e4036") difference() {
        slab(board_d,board_d+pcb_thickness) square(pcb,center=true);
        corners() slab(board_d-e,board_d+pcb_thickness+e) circle(d=3.2);
    }
    color("#252c31") slab(glass_d,board_d) square([95,61],center=true);
    color("#405a67") translate(screen_xy) slab(glass_d-e,glass_d) square(active,center=true);
}
module reference_pico() {
    color("#2e765f") difference() {
        translate([pico_x,pico_y0+25.5]) slab(pico_d-1,pico_d) square([21,51],center=true);
        pico_holes() slab(pico_d-1-e,pico_d+e) circle(d=2.1);
    }
    color("silver") translate([pico_x,pico_y0+3-socket_overhang]) slab(pico_d,pico_d+2.9)
        square([8,6],center=true);
}
module reference_rail() {
    // Simplified 15-series rail showing the mounting face and slot mouth.
    color("#b4b8b9") difference() {
        translate([-90,bolt_y-rail/2,-depth-rail]) cube([180,rail,rail]);
        translate([-91,bolt_y-8.13/2,-depth-8]) cube([182,8.13,8+e]);
        translate([-91,bolt_y-7,-depth-9]) cube([182,14,9-3.05]);
    }
}
module bolt_heads() {
    color("#869097") bolts() difference() {
        slab(seat_d-4,seat_d) circle(d=12);
        slab(seat_d-4-e,seat_d-1.5) circle(d=5.7,$fn=6);
    }
    color("#869097") bolts() slab(seat_d,seat_d+mount_bolt_length) circle(d=6.35);
}
module reference_nuts() {
    color("#767f84") bolts() slab(depth+3.05,depth+7.0) difference() {
        rounded([17,12],1);
        circle(d=6.4);
    }
}
module assembly(spread=0) {
    reference_rail();
    reference_nuts();
    color("#34414a") rear_shell();
    reference_pico();
    translate([0,0,spread/2]) reference_display();
    translate([0,0,spread]) { color("#52616a") faceplate(); bolt_heads(); }
}
if (part=="faceplate") rotate([0,180,0]) faceplate();
else if (part=="rear_shell") translate([0,0,depth]) rear_shell();
else if (part=="fit_front") rotate([0,180,0]) ear_sample() faceplate();
else if (part=="fit_rear") translate([0,0,depth]) ear_sample() rear_shell();
else if (part=="fit_usb") translate([0,0,depth]) intersection() {
    rear_shell();
    translate([pico_x-14,-body.y/2-e,-depth-e]) cube([28,15,depth+2*e]);
}
else if (part=="assembly") assembly();
else if (part=="exploded") assembly(28);
else if (part=="section") intersection() {
    assembly();
    translate([-100,bolt_y-0.8,-depth-rail-1]) cube([200,1.6,depth+rail+10]);
}
else assert(false,str("Unknown part: ",part));
