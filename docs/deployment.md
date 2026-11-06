# Install and update

Production uses two independent Armbian hosts, each connected by USB to its own
Pico 2 W and display. Home uses the Pi 4B as a USB host, with OBS on this PC.
Collect actual host addresses and persistent `/dev/serial/by-id/` paths during
setup; no historical machine name is an installation default.

## Pico

Install MicroPython for the Pico 2 W using its BOOTSEL UF2 procedure on first
setup. Build graphics from the repository root using the README commands.
Stop `pinrig-rig` before uploading: only one process may own USB.
Install mpremote in the deployment environment. In a staging directory, put the
generated graphics directory at `assets/`, copy `pinrig_protocol/commands.py`
as `commands.py`, and copy `firmware/pico/{core,hardware,pixels,storage,main}.py`.
Set `PICO_PORT` to the actual device path, then run:

```sh
mpremote connect "$PICO_PORT" fs cp -r assets :
mpremote connect "$PICO_PORT" fs cp commands.py core.py hardware.py pixels.py storage.py :
mpremote connect "$PICO_PORT" fs cp main.py :
mpremote connect "$PICO_PORT" reset
```

For updates, replace firmware and generated assets together; preserve
`interactions.json` so outstanding tap receipts survive. Upload main.py last.

## Linux host

Python 3.11+ and venv support are required. From the checkout:

```sh
python3 -m venv .venv
.venv/bin/pip install ./pinrig_protocol ./pinrig_host './pinrig_producers[rig]'
```

Install videonode separately. Confirm its actual URL and availability on each
host, including the Pi 4B at home. Missing data remains UNKNOWN; it must never
be interpreted as no consumers. Set `PICO_PORT` to the stable USB path:

```sh
.venv/bin/pinrig-rig --rig rig1 --serial "$PICO_PORT" --bind 0.0.0.0
```

Use rig2 on the second production host. The booth and OBS ingress use port
48194 on the trusted LAN. Choose the intended bind interface; the booth has no
login. For service installation adapt `pinrig-rig.service` paths and arguments
to the actual checkout, user and USB path; ensure its receipt directory is writable.
On updates stop the service, update the checkout and reinstall these packages,
update the Pico if needed, then restart.

## OBS PC

```sh
python3 -m venv .venv
.venv/bin/pip install ./pinrig_protocol './pinrig_producers[obs]'
.venv/bin/pinrig-obs --rig1 "$RIG1_URL" --rig2 "$RIG2_URL"
```

Set URLs to actual host addresses with port 48194. Home testing accepts either
one destination alone. Enable OBS WebSocket (default localhost:4455); configure
`OBS_WEBSOCKET_PASSWORD` and matching `PINRIG_OBS_TOKEN` as needed. Scene names
are `Rig 1`, `Rig 2`, and `MEGA PINBALL`. Adapt `pinrig-obs.service` for the PC.

## Verification and diagnostics

Run the full unit suite from README. Inspect physical pixels and real taps,
booth Send/Clear, OBS scene changes, videonode disconnect/recovery, USB unplug,
host restart and Pico power cycle on each installation. Unit tests do not prove
hardware behavior. Videonode availability at home is unverified until setup.

Run the attended API smoke check with `pinrig-rig` running, OBS reporting paused,
and no existing booth cards:

```sh
.venv/bin/python -m tools.usb_smoke --url "$RIG1_URL" --rig rig1
```

Repeat with rig2 for the second production host; home needs only its configured
rig. Set `PINRIG_OBS_TOKEN` if configured on the rig. The check exercises status,
OBS ingestion, USB delivery, booth Send/Clear and UNKNOWN message retention.
It cancels its own card and leaves OBS evidence unknown; resume OBS reporting
afterward. Do not run during a live event. Real taps, physical pixels and
restart/reconnect checks remain attended checks. No separate host listener or
service is installed; `pinrig_host` is a library embedded in `pinrig-rig`.
