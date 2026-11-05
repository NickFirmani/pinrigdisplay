# Pin Rig Display

The first assembled USB unit is a **Pico 2 W (RP2350)**. Its MicroPython firmware,
build/deployment steps and resource limits are in [firmware/pico](firmware/pico/README.md).
The Linux application below remains the direct-SPI / Pi Zero development path;
it is not the executable installed on the Pico. Both use the same protocol v1
command validator and the same HTTP host. Pico wiring is documented in
[hardware/pinouts.md](hardware/pinouts.md).

Python 3.11+ software for the 480 × 320 Elecrow ST7796 display:

```text
OBS on stream PC → rig PC authority → local HTTP/USB host → Pico 2 W → SPI display
```

Direct-SPI development on the 4B runs the same device command handler over HTTP.
Production producer deployment uses one Armbian tiny PC per rig as the HTTP/USB
host and one Debian stream PC for OBS. See [rig producers and booth setup](docs/rig-producers.md).
Start with the [deployment and acceptance guide](docs/deployment.md): the current
release is ready for an attended pilot, with end-to-end event acceptance still
required on both rigs.
The legacy page API and last-page restoration have been removed. Every device
boot starts UNKNOWN; current state must arrive and its lease must be renewed.

## Implemented

- Protocol v1 shared by local calls, HTTP and newline-delimited USB serial:
  strict validation, boot sessions, bounded deduplication and correlated results.
- ON AIR, CAMERA ACTIVE and CAMERA INACTIVE signs, plus an LCP logo with small
  “Stream Status Unknown” subtext for the `unknown` state; proportional
  500 ms message transitions, steady lettering and subtle sign animation.
- One visible/three pending messages, priority preemption, FIFO ties,
  transition-aware expiry, cancellation and explicit message outcomes.
- Independently installable HTTP host with serial delivery, bounded reconnect,
  freshness-aware lease renewal and explicit uncertain-delivery reporting.
- Separate producer observation policy and HTTP client, per-rig routing,
  freshness, manual selection precedence and stale/unmoderated notice filtering.
- Per-rig state authority, local videonode consumer adapter and booth page;
  a separate OBS generator reports streaming/program-scene state to both rigs.
- Deterministic tests and a hardware-free layout preview command.

The [protocol reference](docs/protocol.md) specifies the implemented contract.
The original [display](docs/display-plan.md), [host](docs/host-plan.md) and
[producer](docs/event-producer-plan.md) plans retain their hardware/integration
roadmaps. See [implementation status](docs/implementation-status.md) for remaining
physical validation and deliberately deferred source/touch integrations.

## Installation and development

Use a virtual environment. From this repository:

```sh
python3 -m venv .venv
. .venv/bin/activate
# Device only: shared protocol + Pillow, no host/producer clients.
python -m pip install ./pinrig_protocol .
# On the SPI-connected Pi, add hardware drivers (and serial for a Zero gadget).
python -m pip install '.[hardware,serial]'
python -m unittest discover -v
python -m display_controller.preview --output /tmp/pinrig-layouts.png
python -m display_controller.server --config config.toml
```

Install DejaVu Sans fonts on the Pi (`fonts-dejavu-core` on Raspberry Pi OS).
A macOS Arial fallback supports local visual checks; actual Pi typography should
be checked using DejaVu. Hardware imports occur only when creating the SPI adapter.

Separate host and producer installations:

```sh
# Host: no Pillow or SPI/GPIO dependencies.
python -m pip install ./pinrig_protocol ./pinrig_host
pinrig-host --serial /dev/serial/by-id/YOUR_DEVICE --bind 127.0.0.1
# Optional producer authority/client, on its own machine/environment:
python -m pip install ./pinrig_protocol ./pinrig_producers
```

Each directory has its own distribution metadata. Build/install the shared
protocol alongside the chosen package; it is not assumed to be on PyPI. The
source checkout allows the full unit suite to import all packages without
installing host-only serial dependencies. Tests never open network/hardware or sleep.

## Send explicit commands

The default listener is loopback port `48193`. The service has no authentication;
configure a deliberate bind address and network access for intended callers.
Both device and host expose `POST /api/commands` and `GET /healthz`.

```sh
curl http://localhost:48193/api/commands -H 'Content-Type: application/json' \
  -d '{"version":1,"request_id":"hello-1","operation":"hello"}'
```

Copy `result.session` into the next command:

```sh
curl http://localhost:48193/api/commands -H 'Content-Type: application/json' \
  -d '{"version":1,"session":"SESSION_FROM_HELLO","request_id":"state-1","operation":"set_state","params":{"state":"on_air","lease_seconds":15,"valid_for":30}}'
```

For synthetic UI scenarios, the included producer client handles the handshake:

```python
from pinrig_producers.client import Client
client = Client("http://localhost:48193")
client.send("set_state", {"state": "on_air", "lease_seconds": 60, "valid_for": 60})
client.send("show_message", {
    "title": "PLAYER READY", "body": "Please approach the machine.",
    "duration": 8, "priority": 2,
})
print(client.send("status", {}))
```

Use `camera_active`, `camera_inactive` and `unknown` to exercise the other signs.
The unknown view shows the logo and caption, shrinking above messages when
present. Unknown state and lease expiry preserve messages; diagnostic details
remain in status responses rather than a display card.
On direct device HTTP, issue a fresh state command before its lease expires.
With verified XPT2046 wiring, enable `touch_enabled = true`. Requires-ack
messages then remain until a fresh press/release anywhere on the screen.
See [touch operation](docs/touch.md) for receipt storage and failure behavior.

## Current SPI wiring on the Pi 4B

| Display | Pi physical pin | BCM/function |
| --- | ---: | --- |
| VCC | 2 | 5 V |
| GND | 6 | Ground |
| CS | 24 | GPIO8 / SPI0 CE0 |
| RESET | 22 | GPIO25 |
| DC/RS | 18 | GPIO24 |
| SDI (MOSI) | 19 | GPIO10 / SPI0 MOSI |
| SCK | 23 | GPIO11 / SPI0 SCLK |
| LED | 17 | 3.3 V |
| SDO (MISO) | 21 | GPIO9 / SPI0 MISO |
| T_CLK | 23 | GPIO11 / SPI0 SCLK (shared) |
| T_CS | 26 | GPIO7 / SPI0 CE1 |
| T_DIN | 19 | GPIO10 / SPI0 MOSI (shared) |
| T_DO | 21 | GPIO9 / SPI0 MISO (shared) |
| T_IRQ | 16 | GPIO23 (connected; polling adapter does not claim it) |

MISO and touch wiring were supplied by the operator and touch SPI responses
were verified on the 4B. The LCD driver still only writes display data. Do not drive the backlight directly
from a GPIO. Confirm and document the Zero 2 W mounting, wiring, and USB power
arrangement before moving the display; this table documents the current setup.
Touch uses pressure polling on CE1 at 100 kHz; the LCD remains on CE0.

## Deployment

The device unit expects `/opt/pinrig-device/bin/display-controller` and
`/etc/pinrig-display.toml`. The host unit expects `/opt/pinrig-host/bin/pinrig-host`
and `/etc/pinrig-host.env`, containing `PINRIG_SERIAL=/dev/serial/by-id/...` and
`PINRIG_BIND=127.0.0.1` (or the intended interface). Create a dedicated `pinrig`
service account and grant only the groups required by that machine: `spi`,
`gpio`, and/or `dialout`. Create the respective virtual environments at those
paths and install the relevant packages. Copy/edit configuration outside Git.

Install the appropriate unit, then run `systemctl daemon-reload` and
`systemctl enable --now display-controller` or `pinrig-host`. Inspect logs with
`journalctl -u display-controller -f` or `journalctl -u pinrig-host -f`.

The Zero must expose an OS-configured USB serial gadget (`/dev/ttyGS0` on the
device, stable `/dev/serial/by-id/...` on the host). Set `serial_path` in device
configuration; HTTP may be enabled simultaneously or disabled. This code does
not change boot firmware, USB gadget configuration, wiring, power, or GPIO
assignments. Confirm the Zero mounting, data-port cable and power ownership
before connecting hardware. The touch wiring above has been exercised on the 4B; the Zero move still needs validation.
