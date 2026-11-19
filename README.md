# Pinrig display

Production uses one OBS PC and two independent Armbian rig PCs. Each rig connects
to its own Pico 2 W over USB. The Pico drives the display and reads touch over
SPI. For home testing, use this PC as the stream host and a Pi 4B as the rig.

| Folder | Purpose |
| --- | --- |
| `shared/` | USB display contracts, artwork and desktop preview, and Linux helpers used by both roles. |
| `display/` | Pico firmware, wiring, and the two enclosure designs. |
| `rig/` | USB host, rig dashboard, local camera reader, sign state policy, and independent software manager. |
| `stream/` | OBS WebSocket integration, stream dashboard, and the client for deploying rig software. |

The stream PC reports OBS state over HTTP. Each rig combines that report with
its local camera state and publishes display commands over USB. The Pico runs
the display and touch logic.

See [installation](docs/deployment.md), [operations](docs/operations.md),
[protocol](docs/protocol.md), [wiring](display/hardware/pinouts.md), and enclosure
assembly for [display 1](display/hardware/enclosure/README.md) and
[display 2](display/hardware/enclosure_2/README.md).

Provision both Picos before leaving for the venue. See
[Provision displays at home](docs/deployment.md#provision-displays-at-home).

Use the [offline installation commands](docs/deployment.md#get-the-source-and-prepare-for-offline-installation)
to install or check the Linux services on each host.

## Development

Run from the repository root with Python 3.11 or later. Pillow and the desktop
artwork package are only needed for asset builds, previews, and tests.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./shared ./rig ./stream .
.venv/bin/python -m tools.build_pico_assets --output /tmp/pico-assets
.venv/bin/python -m shared.artwork.preview --output /tmp/pinrig-layouts.png
.venv/bin/python -m unittest discover -v
```

## Refresh a rig checkout

From the workstation, copy the source and then connect to the rig:

```sh
git clone git@github.com:NickFirmani/pinrigdisplay.git
cd pinrigdisplay
tools/copy-source.sh streamrig@streamrig.lcp
ssh streamrig@streamrig.lcp
```
