# Pin Rig Display Controller

Python software for a 480 × 320 Elecrow ST7796 display. We are currently
validating the UI, artwork, animation, and overall feel with the display wired
directly to a Raspberry Pi 4B over SPI.

The intended setup separates a small display device from its host:

```text
Other event producers → Pi 4B HTTP host → USB serial → Pi Zero 2 W → SPI display
```

The Pi Zero 2 W will mount behind the display when it arrives. The 4B will remain
the host: it accepts events from others and sends explicit display commands.
The display device only needs to produce state signs, render generic messages,
and report command results and interactions. OBS, Twitch, game detection, and
player-selection rules belong outside the device package.

## Plans

- [Display plan](docs/display-plan.md): UI, shared command contract, device behavior,
  and the move from direct SPI on the 4B to the Zero 2 W.
- [Host plan](docs/host-plan.md): the 4B HTTP service, USB delivery, and monitoring.
- [Event producer plan](docs/event-producer-plan.md): OBS and other integrations
  that decide what to tell the host.

These describe planned work. USB serial, the generic message queue, touch
acknowledgment, and the host/producer split are not implemented yet. During
local SPI development, the command contract should mirror the future USB API
so the same scenarios can exercise both setups. Optional HTTP over Wi-Fi on
the device will use that same command handler.

## Current HTTP API

The existing service runs on the SPI-connected 4B, listens on port `48193`, and
restores its last successfully displayed page after restart. It has no
authentication; use it only on a trusted network. Replace `localhost` with the
4B's hostname when calling from another computer.

```sh
curl -X PUT http://localhost:48193/api/display \
  -H 'Content-Type: application/json' \
  -d '{"page":"on_air"}'

curl http://localhost:48193/api/display
curl http://localhost:48193/healthz
```

| Page | Current behavior |
| --- | --- |
| `standby` | Lyons Classic Pinball logo on `#070f20`. |
| `on_air` | Red ON AIR sign with a slow four-second pulse. |
| `camera_active` | Amber CAMERA ACTIVE sign with NOT ON AIR below. |
| `camera_inactive` | Slate INACTIVE sign. |
| `message` | Message page requiring `title` (up to 40 characters) and `body` (up to 240 characters). |

```sh
curl -X PUT http://localhost:48193/api/display \
  -H 'Content-Type: application/json' \
  -d '{"page":"message","title":"Test message","body":"Check the display from across the room."}'
```

Successful updates return HTTP 200. Invalid requests return 4xx JSON errors;
display failures return HTTP 503. The current message page does not implement
the planned temporary card, duration, priority, or acknowledgment behavior.

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

The display is write-only with this wiring. Do not drive the backlight directly
from a GPIO. Confirm and document the Zero 2 W mounting, wiring, and USB power
arrangement before moving the display; this table documents the current setup.
Touch wiring and support have not been established.

## Development

Use Python 3.11 or later. The target Pi needs Pillow and the SPI/GPIO libraries
(`spidev` and a compatible `RPi.GPIO` provider; the hardware extra uses
`rpi-lgpio`). Keep hardware dependencies at the edge so unit tests can run
without a Pi or display.

```sh
python3 -m unittest discover -v
python3 -m display_controller.server --config config.toml
```

Configuration includes the HTTP bind address, SPI/GPIO settings, animation rate,
logo path, and persisted-state path. Relative paths resolve from the
configuration file's directory. Review paths and permissions for the target
machine before starting the service.

## Current systemd service

The supplied unit expects this repository at
`/home/admin/Projects/pinrigdisplay` and runs as `admin` with access to the
`spi` and `gpio` groups. This is the current direct-SPI display service;
a separate host service is planned.

```sh
sudo install -m 0644 display-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now display-controller.service
systemctl status display-controller.service
journalctl -u display-controller.service -f
```
