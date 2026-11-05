# Pico 2 W device firmware

This is the MicroPython port for the **Pico 2 W / RP2350**, not the Linux Pi Zero
2 W. The rig computer runs one `pinrig-rig` service, embedding the `pinrig_host`
USB transport module alongside state coalescing and the booth page.
The existing Linux display service remains available for direct-SPI development.

Pin assignments follow [the soldering pinout](../../hardware/pinouts.md): SPI0
SCK18/MOSI19/MISO16, LCD CS17/DC20/RESET21, touch CS22/IRQ15. The LED is powered
from 3V3; firmware never drives it. Both CS pins are initialized high. A single
loop owns all SPI transactions, holding LCD CS through each complete pixel
transfer. It switches to 100 kHz for touch and restores the 20 MHz requested
LCD speed before drawing. There are no concurrent SPI worker threads.

## Build and deployment

Use the official [Pico 2 W MicroPython firmware](https://micropython.org/download/RPI_PICO2_W/).
The initial hardware test uses v1.29.0 (2026-08-24), ARM build. Install `mpremote`
in a deployment virtual environment. Copy the UF2 to the board's BOOTSEL volume;
it reboots as a USB CDC serial device. This writes firmware, so preserve existing
board data before replacing an established deployment.

Generate graphics on a machine with Pillow and the repository's renderer:

```sh
python3 tools/build_pico_assets.py --output /tmp/pico-assets
```

Copy the contents to `assets/` on the Pico, then copy:

- `pinrig_protocol/commands.py` as `commands.py` (the shared validator, unchanged).
- `core.py`, `hardware.py`, `pixels.py`, `storage.py` from this directory.
- `main.py` last, after validating imports and a test render.

For example, from a prepared staging directory with those files and `assets/`:

```sh
mpremote connect /dev/serial/by-id/YOUR_PICO fs cp -r assets :
mpremote connect /dev/serial/by-id/YOUR_PICO fs cp commands.py core.py hardware.py pixels.py storage.py :
mpremote connect /dev/serial/by-id/YOUR_PICO fs cp main.py :
mpremote connect /dev/serial/by-id/YOUR_PICO reset
```

Stop `pinrig-rig` while using mpremote; only one process may own the serial port.
Do not erase `interactions.json` during upgrades. Graphics are generated files
and are deliberately kept outside Git. The native decoder bounds both input and
output and rejects truncated/oversized blocks. Artwork and fonts are generated
from the current Linux renderer; the output is exact RGB565, not an approximation
of colors. The graphics budget is 2 MB (initial set approximately 1.72 MB).

The host uses the board's persistent `/dev/serial/by-id/...` name. Start
`pinrig-rig --rig rig1 --serial ... --bind 0.0.0.0`;
see [rig setup](../../docs/rig-producers.md). The standalone
`python3 -m pinrig_host.server --serial ...` remains an optional maintenance
tool, used only while the rig service is stopped. The Pico starts UNKNOWN on
every reset and requires fresh leases.

## Contract and resource limits

- Protocol v1 and validation are shared unchanged. USB is newline-delimited UTF-8
  JSON with an 8192-byte frame limit and recovery at the next newline.
- Pico deduplication retains 64 mutations for 15 seconds (advertised in hello),
  instead of the Linux device's 512. A full window rejects new mutations; entries
  are never evicted early. Status and hello remain available. The shorter window
  allows the rig authority's one-second publications and host lease renewals
  without exhausting the cache. Direct USB clients must honor the advertised
  15-second window; the HTTP host independently retains replies for 120 seconds.
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
