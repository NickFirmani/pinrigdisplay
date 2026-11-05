# Implementation status — 5 November 2026

Current release assessment: **ready for an attended pilot**, with end-to-end
acceptance on both Armbian rigs and the Debian stream PC still pending. Start
with [deployment and acceptance](deployment.md). Local software validation is
116 passing deterministic tests plus package and Pico asset-build checks;
physical results recorded below belong to their dated revisions.

The README and protocol reference describe current software. The three original
plans are design roadmaps; their introductory “proposed work” labels do not mean
that the implemented features listed below are still absent.

| Plan area | Status |
| --- | --- |
| Shared contract / direct SPI / optional device HTTP | Implemented, one handler with boot session and bounded request history. |
| Signs, message transitions, priority queue, expiry, cancellation, leases | Implemented; deterministic software and image-layout checks. |
| USB serial delivery | Embedded inside the single `pinrig-rig` service; bounded deadlines/backoff, durable tap receipts and explicit uncertain delivery. Standalone HTTP host remains a maintenance tool. |
| Packaging and systemd templates | Separate protocol/device/host/producer distributions; installation-specific paths documented. |
| Producer authority | Explicit, per-rig, fresh observations; conservative resolver, manual selection policy and message filtering. |
| Live OBS/videonode/booth adapters | Implemented for the agreed two-rig deployment: top-level OBS program scenes plus streaming, videonode SSE consumer counts, per-rig authority and local booth tap/clear page. See [rig producers](rig-producers.md); live deployment validation remains. Twitch and general scene-graph interpretation remain deferred. |
| Touch and durable interaction outboxes/storage | XPT2046 any-screen tap verified on the 4B; bounded durable device outbox and host receipt/confirmation implemented. Coordinate targeting/calibration remains deferred. |
| Pico USB deployment | Initial USB/display/touch baseline recorded below on media-pi. Current Pico fixes and two-rig deployment require attended acceptance. The Pi Zero path is optional Linux development work. |

## Linux direct-SPI / optional Zero acceptance checks

These are integration checks, not part of the default unit suite:
For the current Pico/two-rig rollout, use [deployment acceptance](deployment.md)
instead of treating the historical Zero roadmap as the installed topology.

1. On the current SPI 4B, exercise each state, message expansion/return, interrupted
   transition, preemption and lease expiry using the README commands. Verify
   compact lettering, 22 px body text and ellipsis from the intended distance.
2. Inspect `last_render_seconds` and animation cadence. The loop skips missed
   periods instead of catching up; changed-region writes skip unchanged pixels.
   Lower animation FPS before increasing bus load. No automatic SPI speed changes.
3. Confirm the Zero SPI pins, physical mounting and power ownership, then configure
   its USB gadget using the installed OS documentation. Record the verified setup
   here before moving the display. Do not connect competing USB/pin power sources
   without checking the intended power arrangement.
4. Verify both boot orders, cable unplug/replug, host/device restart, stale upstream
   evidence, concurrent optional HTTP and sustained operation. Check that old
   transient messages never replay and a stale state becomes UNKNOWN.
5. Verify the implemented fresh press/release binding, device acknowledgment
   outbox, host durable storage and confirmation recovery on each assembled unit.

The first producer contract is `pinrig_producers.policy.Observation`: source, rig,
monotonic observation time, confirmed live contribution and confirmed local use.
Unknown is `None`; missing/stale evidence is never negative evidence. One
configured authority supplies an explicit required-source set per rig. Adapters
use the agreed top-level OBS scene convention for this deployment; general
nested-scene/visibility/transition interpretation remains deferred. Videonode
consumers establish local use. No live service adapter is enabled implicitly.

## Direct-SPI Pi 4B test — 30 October 2026

Ran the complete unit suite on the connected Pi (Python 3.13.5, Pillow 11.1.0):
49 tests passed. The separately invoked `tools/hardware_smoke.py` exercised real
HTTP commands and the SPI display driver. States, message transitions/expiry,
state changes during messages, duplicate requests, priority replacement, three
pending slots, overflow rejection, cancellation, FIFO selection, unsupported
acknowledgment and lease-loss UNKNOWN all passed their API assertions. No display
faults or automatic service restarts were reported.

A separate service restart check confirmed UNKNOWN startup, a new session and
rejection of commands bearing the old session. This verifies software/driver
results, not physical pixel correctness; visual readability and motion await an
observer's confirmation. The original SPI wiring and 20 MHz speed were unchanged.
Animated sign encoding/write samples were approximately 153–164 ms, so actual
cadence is below the configured 8 FPS. This is a baseline, not a sustained-load
or Zero/USB result. The current test uses an isolated release and a temporary
systemd runtime override; the original installation remains available.

To repeat the attended physical test against the local device HTTP listener:

```sh
python3 tools/hardware_smoke.py
```

This integration script intentionally performs real HTTP requests and delays,
changes the physical display, and ends with lease-expired UNKNOWN. It is excluded
from unit-test discovery.

### Transition performance follow-up

An observer reported choppy message entrance/exit scaling. RGB565 conversion now
uses Pillow channel operations instead of a Python pixel loop. The render loop
includes rendering time in its frame budget, with a separate up-to-30-FPS target
for layout transitions (actual SPI throughput still limits the rate). No SPI
speed or electrical settings changed. All 52 unit tests passed locally and on
the Pi. Six physical message cycles remained healthy; compact writes sampled
24–27 ms and median full-size encoding/write time was 73 ms, versus roughly
160 ms before. Two full-size samples were slower (138 and 283 ms), so these
measurements do not establish consistent motion or replace visual confirmation.

Pulse-pause correction: scaling previously substituted animation time zero,
which changed brightness at entry and jumped back to live phase at exit. The
controller now freezes its accumulated pulse phase during layout motion and
resumes from that phase after the final layout frame. Interrupted transitions
retain the same phase. The expanded suite contains 54 tests, including opening,
closing and interrupted-layout phase continuity.

## Pico 2 W USB deployment — 5 November 2026

The assembled unit is a Raspberry Pi **Pico 2 W (RP2350)**, not a Pi Zero 2 W.
The operator authorized a MicroPython port. See [firmware/pico](../firmware/pico/README.md)
for the build, exact pin assignments, flash/RAM limits and deployment procedure.
The old Linux direct-SPI implementation remains in the repository.

The board was initially detected in RP2350 BOOTSEL mode. Official Pico 2 W
MicroPython v1.29.0 was installed, followed by the shared command validator,
device state machine, SPI/touch adapter, durable flash outbox and generated
artwork/font assets. The bootloader did not expose a CURRENT.UF2 backup file.
Media-pi now runs the enabled `pinrig-host` service over a stable USB serial
identity; its old direct-SPI `display-controller` service is disabled and its
configuration retained for rollback. Machine-specific deployment files remain
on media-pi, not in Git.

Observed hardware results:

- The operator confirmed the initial UNKNOWN logo was correct and uncorrupted.
- Actual USB state commands, duplicate message delivery and timed expiry passed.
- HTTP-to-USB operation passed with the installed host service.
- A real booth-card tap was acknowledged, stored durably on the host and confirmed
  to the Pico. The operator confirmed dismissal and a clean ACTIVE sign afterward,
  with none of the previous shared-bus blue lines.
- Native graphics decoding rejected malformed input on the board. Full-frame
  ACTIVE rendering measured about 331 ms, and a message frame about 461 ms;
  approximately 219 KB heap remained after the card render.

The first port deliberately uses four layout sizes and three pulse levels within
its 1.72 MB graphics budget. Transitions are stepped and slower than the Linux
renderer. This is a functional baseline, not a claim of smooth animation or
long-duration reliability. Wi-Fi control and position-sensitive touch are not
implemented on the Pico. No bus speed, power or backlight pin was increased.

Pico follow-up: the first physical queue test exposed MicroPython's unstable
equal-key sorting. Pending messages now use an explicit arrival sequence as a
secondary key. At the operator's request, both device implementations now pause
pulsation for the entire visible-message lifetime, resuming after closing.
This avoids repeated full-frame redraw behind a stationary card.

## Deployment review — 5 November 2026

The Pico now matches the Linux device's UNKNOWN message behavior: visible and
queued cards survive both explicit UNKNOWN and lease expiry, new messages are
accepted and tap/clear remain available. UNKNOWN artwork now has four layout
sizes; deploy the rebuilt assets and firmware together.

The Pico retry window is now 15 seconds for 64 commands, advertised by hello.
The earlier 120-second window filled during normal producer/host traffic.
A deterministic five-minute host/authority/Pico test covers repeated state
publication, renewals and booth send/clear without capacity failure. HTTP host
and Linux-device retry windows remain 120 seconds/512 commands. Current assets
use 1,838,272 bytes on the review machine, within the 2 MB budget. These changes
have not been physically deployed or accepted by this review.

## Combined rig service — 5 November 2026

Production now runs one `pinrig-rig` service per rig. State coalescing and USB
delivery communicate through an in-process client; the host module still owns
validation, deduplication, freshness-aware renewal, reconnects and durable tap
receipt confirmation. There is no separate localhost host listener in normal
operation. The `[rig]` install extra adds USB dependencies; the stream-PC `[obs]`
install remains independent of them.

The new unit runs as `pinrigdisplay:pinrigdisplay`, with `dialout` access and
the existing `/var/lib/pinrig-host` receipt directory. Migration disables the
old host service, copies its serial path into the rig environment file and
preserves the receipt database while assigning ownership to `pinrigdisplay`. Shutdown
drains HTTP handlers and source workers before closing USB. The full 116-test
suite includes local-client uncertain-delivery deduplication, receipt storage,
listener-startup failure and orderly worker/USB shutdown. Physical acceptance of
the combined process remains part of the attended deployment checklist.
