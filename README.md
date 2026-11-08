# Pinrig display

Production: OBS PC → two independent [Armbian tiny PC → USB → Pico 2 W → SPI → display].

Home testing: this PC → Pi 4B → USB → Pico 2 W → SPI → display.

The stream PC runs `pinrig-stream`: OBS reporting plus an overview of one or
more rigs and rig software installation. Each rig runs `pinrig-rig`, embedding
`pinrig_host` USB delivery and serving its booth/status page and display firmware
installer. Rig software updates use an authenticated management API that stays
available during display-service restarts; bootstrap installs it locally. The Pico alone controls SPI and touch; it has no webpage.

See [install/update](docs/deployment.md), [operations](docs/operations.md),
[protocol](docs/protocol.md), [touch](docs/touch.md), and [wiring](hardware/pinouts.md).

Desktop artwork tools require Pillow; host and producer installs do not:

```sh
python3 -m venv .venv
.venv/bin/pip install ./pinrig_protocol .
.venv/bin/python tools/build_pico_assets.py --output /tmp/pico-assets
.venv/bin/python -m pinrig_artwork.preview --output /tmp/pinrig-layouts.png
.venv/bin/python -m unittest discover -v
```
