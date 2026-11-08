# Pico 2 W firmware

Setup and updates: [deployment guide](../../docs/deployment.md).
Wiring: [authoritative pinout](../../hardware/pinouts.md).

## Contract and resource limits

- Protocol v1 and validation are shared unchanged. USB is newline-delimited UTF-8
  JSON with an 8192-byte frame limit and recovery at the next newline.
- Pico deduplication retains 64 mutations for 15 seconds (advertised in hello),
  A full window rejects new mutations; entries
  are never evicted early. Status and hello remain available. The shorter window
  allows the rig authority's one-second publications and host lease renewals
  without exhausting the cache. Direct USB clients must honor the advertised
  15-second window; the host independently retains replies for 120 seconds.
- One visible plus three pending messages; higher priority preempts, equal
  priority is FIFO. Timers start after successful opening; requires-ack cards
  have no timed expiry. UNKNOWN and lease expiry preserve visible/queued cards,
  accept new messages and retain tap/clear behavior. The unknown logo shrinks
  above a visible message. All four states switch directly between layouts.
- Touch is pressure-based, anywhere on screen. A fresh press/release binds to
  the visible, settled card. Eight acknowledgments persist via atomic LittleFS
  replacement with sync before success. Host confirmation removes each receipt.
- Receipt IDs and boot sessions are random 128-bit IDs. The latest 16 terminal
  message outcomes are reported. Flash receipt writes occur only on interactions
  and confirmations, never on animation frames or lease renewal.
- Fonts include printable ASCII, ellipsis and an explicit missing-glyph box.
  Accepted Unicode stays verbatim in command data; unsupported glyphs show boxes.
  Text wraps/ellipsizes at fixed font sizes. The acceptance response advertises
  this rendering policy.
- USB is the only command transport in this port. Wi-Fi is not configured.
  Ctrl-C remains reserved for mpremote maintenance; the trusted host sends JSON,
  not raw REPL controls.

Run `python3 -m unittest discover -v` for hardware-free scheduler/codec tests.
Physical acceptance additionally requires visual inspection, real taps, USB
reconnect/host restart and a power cycle. API health cannot detect bad wiring or
wrong physical pixels.

## Sign artwork and motion

Each state has two base images at brightness level zero. `STATE-3-0.r` fills
the 480 × 320 screen. When a message appears, the renderer reads the top 188
rows of `STATE-0-0.r` and draws the message card in the remaining 132 rows.
Replacing a card with the same sign updates only the card area.

ON AIR, CAMERA ACTIVE and CAMERA INACTIVE each use four barberpole phases
(`STATE-motion-0.bin` through `STATE-motion-3.bin`), stepping every 750 ms
while the sign fills the screen. The lettering stays still. Motion pauses while
a card is visible and resumes after the last card closes. UNKNOWN stays static.

The release builder packages eight base images, twelve motion files, two fonts
and their metrics together. Build each release in a fresh directory and install
the matching firmware and assets using the [deployment guide](../../docs/deployment.md).

Changed pixels are grouped into 10-pixel tiles, merged horizontally into 78 / 61 / 67
windows for ON AIR / ACTIVE / INACTIVE, respectively, sending
115,200 / 121,600 / 121,600 pixel bytes per phase. This trades retransmission of some
steady pixels for fewer windows than the original 580 exact dirty rectangles.
Four compressed phases for the current state are cached in RAM on first use to avoid subsequent flash
reads. The cache is replaced when the state changes to bound memory use. The first motion timing includes loading that cache. `PDM2` assets contain
little-endian x/y/width/height uint16 records followed by a uint16 compressed
length and a run/literal RGB565 block. Failed updates invalidate the full image
cache. Missed phases are skipped; SPI remains requested at 20 MHz.

Status exposes the latest `motion_seconds` and successful image/motion payload
bytes (excluding address commands and message-card writes). USB and touch are
serviced between updates. Hardware timing and visual acceptance remain necessary.
Synthetic testing renews a real state lease; stopping its source restores UNKNOWN.

ACTIVE and INACTIVE stripe colors match ON AIR’s relative luminance contrast
against the panel face at each brightness level, preserving their amber/blue hues.
