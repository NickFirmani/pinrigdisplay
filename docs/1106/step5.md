# 5. Design and print a serviceable enclosure

Recommendation: start with dimension-driven parametric CAD and AI-assisted
editing. Keep mounting holes, display opening, clearances, and USB access as
named parameters. The following is a current tool shortlist, not a claim that
any generator can produce a mechanically verified case from a prompt.

| Route | Cost model and fit for this case |
| --- | --- |
| [OpenSCAD](https://openscad.org/) + coding assistant | Free CAD software; assistant cost depends on the tool. Simple text-defined solid geometry is a practical default for a two-piece enclosure. |
| [build123d](https://build123d.readthedocs.io/en/latest/) + coding assistant | Open-source Python parametric CAD; useful for precise solids and a source-controlled design. Prefer this if STEP exchange and richer CAD operations matter. |
| [Zoo Design Studio / Zookeeper](https://zoo.dev/zookeeper) | Conversational CAD agent with geometry inspection tools. Best dedicated AI CAD candidate to trial against the same measured enclosure brief. [Free/paid plans and metered AI usage](https://zoo.dev/zoo-pricing); verify current included usage before buying. |
| [Autodesk Fusion](https://www.autodesk.com/products/fusion-360/personal) | Conventional CAD with automated modeling in the paid offering; limited free personal-use eligibility. A strong manual refinement route; do not assume paid automation is included in the free edition. |
| [Meshy](https://www.meshy.ai/pricing) / [Tripo](https://www.tripo3d.ai/pricing) | Free entry tiers and paid generation/export allowances. Useful for decorative form exploration. My recommendation is to rebuild critical fits in parametric CAD rather than trust a generated mesh's dimensions. |

Sources checked 6 November 2026. Exact subscriptions and export allowances change;
choose using a small trial, not a long subscription or a visual demo alone.

Collect measurements before modeling: exact display PCB/glass outlines, hole
centers and diameters, board thicknesses, component/connector heights, soldered
wire routing, Pico position, USB plug and bend clearance, and BOOTSEL access.
Also record printer model/build volume, nozzle, material, mounting location,
viewing angle, and whether the case needs a stand or attachment to the rig.
Do not infer physical dimensions from the 480 × 320 resolution.

Design a front bezel and removable rear shell with board supports, cable strain
relief, no pressure on the touch glass, and accessible USB/BOOTSEL. Confirm screw
or insert dimensions and print clearances with the available printer. Keep the
documented wiring and power arrangement. Use small hole/clearance and bezel
fit-test prints before the complete case; then check cable insertion, touch
access, stability, service access, and sustained-operation temperature.

Deliver editable CAD source, dimension notes, printable STL/3MF, STEP where the
chosen CAD supports it, a fastener list, print orientation/settings, and a short
assembly guide with photos of the fitted hardware.