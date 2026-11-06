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
  above a visible message, using the same four layout steps as the other signs.
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
- The first firmware uses four pre-rendered layout sizes and three pulse levels
  to stay within flash/RAM budgets. Pulse phase freezes during layout motion and while any message is visible;
  it resumes only after the card closes.
  It is not frame-for-frame equivalent to Pillow's continuous scaling.
- USB is the only command transport in this port. Wi-Fi is not configured.
  Ctrl-C remains reserved for mpremote maintenance; the trusted host sends JSON,
  not raw REPL controls.

Run `python3 -m unittest discover -v` for hardware-free scheduler/codec tests.
Physical acceptance additionally requires visual inspection, real taps, USB
reconnect/host restart and a power cycle. API health cannot detect bad wiring or
wrong physical pixels.

When upgrading an earlier build, replace the generated assets together with the
firmware: UNKNOWN now requires `unknown-0-0.r` through `unknown-3-0.r`. The old
single UNKNOWN image is insufficient. Preserve `interactions.json`, stop the USB
host for the upload, and run the attended acceptance checks in
[deployment](../../docs/deployment.md) before event use.
