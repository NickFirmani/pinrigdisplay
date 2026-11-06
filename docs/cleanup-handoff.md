# Cleanup and usability handoff

6 November 2026. Planning only; no runtime or installed-device changes.

## Outcome and supported setups

Make this a small, dependable display system that a person can install, update,
diagnose, and use without an assistant interpreting the instructions.

Production, following the owner's explicit diagram:

```text
OBS PC → two independent [Armbian tiny PC → USB → Pico 2 W → SPI → display]
```

Home testing:

```text
This PC → Pi 4B → USB → Pico 2 W → SPI → display
```

The Pi 4B is still a supported test host. Its former direct-SPI display role is
a retirement candidate. The Pico is the display controller; the Linux computer
is the host. Keep those names distinct. Keep source interpretation on the PCs.
Confirm the OBS PC OS and home source/test method before writing OS-specific
install commands; the existing Debian/systemd instructions are not proof of
the actual stream-PC OS. Do not invent hostnames or require a second home rig.

## 1. Establish what is dead, then remove it

Start with this evidence-based inventory. “Candidate” does not mean proven unused.
Check imports, entry points, assets, packaging, tests, docs, and the supported
installation paths before deleting code. Git history is enough for obsolete plans.

| Item | Finding and disposition |
| --- | --- |
| `AGENTS.md` purpose; Zero migration sections in `README.md`, `docs/display-plan.md`, `docs/host-plan.md`, `docs/implementation-status.md` | Stale target architecture. Replace with the two setups above; remove the Zero rollout roadmap. Clarify Pico GP numbering versus Linux BCM numbering. |
| `docs/deployment.md`, `docs/rig-producers.md`, Pico README | Overlapping setup and migration narratives. Consolidate into one current install/update guide. Remove old two-process migration and mandatory backup/restore from the normal path. |
| `media-pi`, `rig1.local`, `rig2.local`, historical machine-specific acceptance claims | Historical evidence/examples, not verified current hosts. Remove from active commands; retain only useful dated measurements outside the quick start. Collect actual addresses during setup. |
| `display_controller/server.py`, `api.py`, `config.py`, `serial.py`, `touch.py`, `display/st7796.py`, `display-controller.service`, `config.toml`, `tools/hardware_smoke.py` | Old Linux display runtime candidates. Retire after extracting the build/preview dependencies and replacing any useful test fixtures. Home USB hosting does not need these SPI drivers. |
| `display_controller/controller.py`, `tests/helpers.py`, Linux-device tests | Linux controller doubles as a test reference/fake today. Migrate relevant host integration coverage to explicit fakes or the Pico core before removing it. Do not keep an entire obsolete product merely as a fixture. |
| `display_controller/display/pages.py`, `renderer.py`, artwork, `preview.py`, `tools/build_pico_assets.py` | Still useful: Pico asset generation imports `PageRenderer`, `_font`, and `encode_rgb565`. Extract the needed desktop build/preview code before removing the Linux package. |
| `pinrig-host.service`, `pinrig_host/server.py`, `pinrig_producers/client.py`, `tools/usb_smoke.py` | Optional maintenance HTTP path; smoke tooling currently uses it. Decide whether to retain one clearly separated diagnostic tool or replace it with direct USB diagnostics, then remove the unused listener/unit/client together. |
| `pinrig_host/service.py`, `delivery.py`, `client.py`; `pinrig_protocol/` | Live production dependencies. `pinrig-rig` imports `Host`, `SerialDelivery`, and `LocalClient`. Keep; the package name does not imply an obsolete extra service. |
| `pinrig_producers/obs.py`, `authority.py`, `rig.py`, `videonode.py`, `booth.html`, rig/OBS units | Live path. Keep two-rig production support. OBS currently requires both destinations; allow one configured destination for home testing. Confirm videonode availability at home without fabricating negative evidence. |
| `docs/event-producer-plan.md`, `docs/touch.md`, `docs/protocol.md`, generated demo GIFs | Preserve current contracts and wiring facts in concise references. Remove superseded roadmap prose and animations that misrepresent the Pico UX. |
| `hardware/pinouts.md` | Current Pico wiring, but repeated tables and C-style constants duplicate the same facts. Keep one authoritative table, shared-bus notes, and connector reference. |

Deliver a short final removal list with a reason per item, followed by focused
deletions. Adjust package metadata, tests, commands, and links in the same change.
Do not treat the existing 116 tests as proof of hardware behavior or dead-code
coverage. The full suite passes locally at this planning baseline.

Done when both supported setups use an explicit, small dependency graph, no
active instructions point to retired machines, and useful test/build behavior
survives the cleanup.

## 2. Make low-bandwidth motion intentional

Current evidence: `firmware/pico/hardware.py` selects among three pulse levels
and four layout sizes. Every changed render writes a 480 × 320 RGB565 image;
a visible card is written afterward. `core.py` uses a 500 ms geometry transition.
This suggests avoidable redraw and flashing risk, not a confirmed explanation
for every reported visual problem. Measure on the assembled Pico.

At the requested 20 MHz SPI rate, a full 307,200-byte image takes at least
123 ms on the wire, before asset reads, decoding, drawing, and other work.
Half-screen updates still cost about 61 ms. A 480 × 8 strip costs about 3.1 ms.
These are calculated transfer bounds, not measured refresh rates.

First add a small hardware benchmark: record bytes written, total render time,
USB response time, and touch responsiveness for idle, state change, message
arrival, and dismissal. Record actual SPI rate if available. Keep the existing
20 MHz requested setting during comparisons.

Prototype these in order, keeping sign lettering steady:

| Experiment | Proposed behavior | Decision criterion |
| --- | --- | --- |
| Small heartbeat | Two to four positions/segments near the sign, stepping every 250–500 ms | Cheapest baseline; visible at the intended viewing distance without looking like an alarm. |
| Barberpole / marching border | Shift diagonal marks through a narrow strip or housing edge in discrete phases | Preferred visual candidate; update only the strip, not half the screen. |
| Stepped scan band | Move a subtle highlight through four to eight positions in the sign housing | Try if it reads as deliberate at low cadence; redraw old and new band regions only. |
| Alternating upper/lower housing | Alternate small accents on the two halves | Compare to the requested half-icon idea; reject if it appears broken or obscures state. |

The panel scans its own memory independently of SPI writes. A top-to-bottom
write is not guaranteed to track visible scanout, especially after rotation.
The ST7796S exposes tearing-effect and scrolling controls, but the documented
module connection has no TE signal. Do not base the normal effect on unverified
scan synchronization. Build the visual effect explicitly with address-window
writes; investigate true scan-timed effects only as a bounded hardware experiment.
[ST7796S datasheet](https://files.waveshare.com/wiki/common/ST7796S_Datasheet.pdf).

Useful precedents: GIMP's moving selection outline demonstrates a small animated
border; LVGL documents rendering and flushing small regions; TFT_eSPI's terminal
example uses controller scrolling on an ILI9341. These are design/implementation
references, not evidence that the same scrolling configuration works on this
landscape ST7796S module. No framework migration is required.
[GIMP](https://docs.gimp.org/2.10/en/gimp-tool-rect-select.html),
[LVGL](https://lvgl.io/docs/open/9.2/porting/display.html),
[TFT_eSPI example](https://github.com/Bodmer/TFT_eSPI/blob/master/examples/320%20x%20240/TFT_Terminal/TFT_Terminal.ino).

The cue must not imply fresh source state merely because an animation timer
runs. Tie normal-state motion to a valid state lease; switch to an unmistakable
UNKNOWN presentation on expiry. Keep the cue visible with messages if it remains
cheap and unobtrusive. State changes, touch, and USB take priority over motion;
skip missed steps instead of replaying them.

Done when the owner selects a physical-display prototype, unchanged lettering
is not retransmitted for the cue, and measured command/touch latency remains
acceptable under sustained use. Test dirty rectangles, fake-clock phase changes,
lease expiry, missed frames, and failed writes deterministically.

## 3. Rework message presentation

Use two stable layouts: full sign, and compact sign above a fixed message card.
Start with immediate appearance/disappearance. Remove smooth scaling/fading as
a requirement; there is no need to simulate smooth animation in four large jumps.
Compose the final regions without first erasing the message area with a full
background image. Avoid redrawing an unchanged sign when replacing card text.

Use physical examples: short message, 240-character booth message, long word,
newlines, unsupported characters, acknowledgment prompt, queue replacement,
UNKNOWN plus message, and touch/storage failure. Check wrapping (currently
character-based), clipping, line spacing, contrast, and reading distance.
Keep the acknowledgment instruction from consuming the entire title line.

Preserve priority/FIFO rules, cancellation versus acknowledgment, message
retention on UNKNOWN, and fresh press/release binding. Start timed duration
after the final card is successfully drawn. Update the protocol wording and
tests when removing transition timing. A failed render must not report visible
success or consume the reading interval.

Done when opening/closing/replacing cards has no visible blank intermediate
screen, the state remains readable, and a real tap works during normal use.
Add regression tests for lifecycle, geometry, layout boundaries, and errors;
use an attended test for physical pixels and touch.

## 4. Install, reflash, and diagnose without guesswork

Provide a supported release bundle containing matching Pico code/assets and
version information. A user should not assemble a staging directory, discover
hidden imports, or build fonts merely to install the display.

Write one numbered path per machine, with commands labeled by where they run,
the few required values collected once, expected output, and a short recovery
step. Provide separate first-install and update sections. Proposed tooling must
be implemented and tested before instructions present it as available.

| Machine | Required operator workflow |
| --- | --- |
| Pico/display | Connect USB; enter BOOTSEL if needed; install the chosen runtime and complete release; reset; verify UNKNOWN and version. Distinguish a runtime UF2 from a complete application install. |
| Armbian host / home Pi 4B | Install prerequisites and one rig service; select the detected USB device; configure rig identity/source endpoints; start service; open status page. Detect an existing service account so rerunning setup works. |
| OBS PC / home source PC | Enable/configure OBS WebSocket when used; install and start the producer; select one or two host destinations and scene mappings; show connection and delivery status. Use instructions matching its actual OS. |

Make clean reinstallation the recovery path. No mandatory device backup,
receipt migration, or old-environment restoration workflow. Reflashing may
discard pending messages and unconfirmed tap receipts; say this once plainly.
Distinguish that deliberate maintenance reset from ordinary reconnect/restart,
where existing durable receipt guarantees should continue to work. Still stop
the USB-owning host service during uploads and restart it afterward.

Expand the existing booth/status view rather than creating another service:
show OBS connection/authentication status, current program scene and streaming
state, last fresh observation age, per-rig report success, videonode status,
USB connection, installed versions, displayed state, and actionable last error.
Some of these fields require new producer/status data; they are not currently
available just by relabeling the UI. Never display credentials.

Include explicit checks for OBS closed, wrong password, unrecognized scene,
one unreachable rig, USB unplug, stale source, firmware fault, and failed tap
storage. Distinguish process running, source fresh, command accepted, display
rendered, and person acknowledged. Explain where logs live and give one command
to read them on each supported OS.

Documentation target: README about one screen with topology and entry links;
one installation/update guide; one short operation/troubleshooting guide;
one protocol reference; one wiring reference. Link to details instead of
repeating them. Remove obsolete plans after extracting still-needed decisions.

Done when a person can install from a clean machine, update, reflash, and find
the cause of a disconnected display using only the guide. Validate first on
the home chain, then both production rigs. Test installer reruns and failure
messages, producer single/two-destination behavior, and status freshness.

## 5. Design and print a serviceable enclosure

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

## Handoff sequence and completion

1. Confirm machine inventory, source availability, and removal decisions; capture
   Pico performance/readability baseline before changing rendering.
2. Extract the asset/preview dependencies, then retire obsolete runtime and docs.
3. Implement stable message layouts and partial updates; compare small motion
   prototypes on hardware and select one with the owner.
4. Package installation/update tooling and useful OBS/host diagnostics; write
   the concise guide against the actual working commands.
5. Measure and prototype the enclosure; mechanical work can proceed independently
   once board placement, cable routing, and service access are known.
6. Run the full unit suite, package/build checks, clean-install exercises, and
   attended end-to-end checks on home and production setups. Record revision,
   hardware, measured timings, and observed results in one short acceptance note.

Keep commits focused. Every behavioral change needs relevant deterministic
tests, and physical acceptance stays separate. No new deployment topology,
electrical changes, Wi-Fi transport, or wholesale graphics-framework rewrite is
needed to complete this plan.
