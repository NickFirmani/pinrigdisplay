# Pin Rig Display Controller

A small Python service that drives a 480x320 Elecrow ST7796 display and exposes
page selection over a LAN HTTP API. It restores the last successfully displayed
page after a restart.

## Pages (update me)

- `standby`: the Lyons Classic Pinball logo on `#070f20`.
- `on_air`: a retro ON AIR light with a slow four-second pulse.
- `camera_active`: a matching amber CAMERA ACTIVE sign with NOT ON AIR below.
- `camera_inactive`: a matching slate sign labeled INACTIVE.

![Camera active sign](assets/camera-active.png)
![Inactive sign](assets/inactive.png)

## API

The service listens on TCP port `48193` without authentication. It is intended
for a trusted local network.

```sh
curl -X PUT http://media-pi-2.local:48193/api/display \
  -H 'Content-Type: application/json' \
  -d '{"page":"on_air"}' # (one of [standby, on_air, camera_active, inactive, 

... update me
```

# Page Types


Read the current state or service health:

```sh
curl http://media-pi-2.local:48193/api/display
curl http://media-pi-2.local:48193/healthz
```

Successful updates return HTTP 200. Invalid requests return 4xx JSON errors;
display failures return HTTP 503.

## Wiring

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

The display is write-only with this wiring. Do not connect the backlight directly
to a GPIO; dimming requires suitable switching hardware.

## Development

The target Pi needs the Debian packages that provide Pillow, `spidev`, and
`RPi.GPIO`. Run the deterministic test suite with:

```sh
python3 -m unittest discover -v
```

Run the service in the foreground with:

```sh
python3 -m display_controller.server --config config.toml
```

Configuration includes the HTTP bind address, SPI/GPIO settings, animation rate,
logo path, and persisted-state path. Relative paths are resolved from the
configuration file's directory.

## systemd

The supplied unit expects this repository at
`/home/admin/Projects/pinrigdisplay` and runs as `admin` with access to the
`spi` and `gpio` groups.

```sh
sudo install -m 0644 display-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now display-controller.service
```

Inspect it with:

```sh
systemctl status display-controller.service
journalctl -u display-controller.service -f
```
