# Architecture Definition

Production, following the owner's explicit diagram:

```text
OBS PC → two independent [Armbian tiny PC → USB → Pico 2 W → SPI → display]
```

Home testing:

```text
This PC → Pi 4B → USB → Pico 2 W → SPI → display
```

The Pi 4B is still a supported test host. The Pico is the display controller; the Linux computer
is the host. Keep those names distinct. Keep source interpretation on the PCs.
Confirm the OBS PC OS and home source/test method before writing OS-specific
install commands; the existing Debian/systemd instructions are not proof of
the actual stream-PC OS. Do not invent hostnames or require a second home rig.

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