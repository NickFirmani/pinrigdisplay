# Pinrig display

Production: OBS PC → two independent [Armbian tiny PC → USB → Pico 2 W → SPI → display].

Home testing: this PC → Pi 4B → USB → Pico 2 W → SPI → display.

Each Linux host runs `pinrig-rig`, embedding `pinrig_host` USB delivery and
serving the booth page and OBS reports. The Pico alone controls SPI and touch.
OBS runs separately on the source PC. Firmware uses the shared command validator;
installing it requires no Linux host or producer packages.

See [install/update guide](docs/deployment.md), [protocol](docs/protocol.md),
[touch](docs/touch.md), and [wiring](hardware/pinouts.md).

Desktop artwork tools require Pillow; host and producer installs do not:

```sh
python3 -m venv .venv
.venv/bin/pip install ./pinrig_protocol .
.venv/bin/python tools/build_pico_assets.py --output /tmp/pico-assets
.venv/bin/python -m pinrig_artwork.preview --output /tmp/pinrig-layouts.png
.venv/bin/python -m unittest discover -v
```
