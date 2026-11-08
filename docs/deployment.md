# Install and update

Production: one Linux stream PC → independent Armbian rig PCs → USB → Pico 2 W
→ display. Home: this PC → Pi 4B → USB → Pico → display. Collect actual rig
addresses, management API URLs, USB paths and OBS scene names; examples below are placeholders.
The rig page uses port 48194; the stream overview uses 48195 by default.

## 1. Prepare releases (build machine)

Use Python 3.11+. For Linux software bundles, build on the target Linux
architecture and Python version. Network access is needed when building wheels;
installation uses the resulting offline wheelhouse. Debian-family prerequisites
on both PCs are `python3`, `python3-venv`, and systemd; rig PCs also need
the `dialout` group. Install these with the machine's package manager first.

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install ./pinrig_protocol ./pinrig_host './pinrig_producers[rig,obs]' .
.venv/bin/python -m tools.build_software_release --output /tmp/software-RELEASE --release RELEASE
.venv/bin/python -m tools.build_release --output /tmp/display-RELEASE --release RELEASE \
  --runtime /path/to/pico2w.uf2 --runtime-version 1.29.0
```

Choose an immutable release name, such as a date plus revision; each output
must be a new directory. Use the [official Pico 2 W MicroPython runtime](https://micropython.org/download/RPI_PICO2_W/)
matching `--runtime-version`. A display release includes its UF2, application,
shared validator, all static/motion graphics, fonts, identity and checksums.
Pillow/fonts are build dependencies only. Keep release directories out of Git.
Hashes detect damaged payloads; stage releases only from a trusted build source.

Expected: software wheels and `software.json`; display `manifest.json`,
`runtime.uf2`, firmware and `assets/`. Both builders fail on missing build inputs.
If a build fails, remove that incomplete output directory and rebuild.

## 2. Bootstrap the stream PC (on that Linux PC)

Copy the matching software bundle onto the PC. Create a private configuration
file outside the checkout. Generate two credentials with
`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`, once for OBS
reports and once for maintenance; substitute them into this JSON:

```json
{
  "role": "stream",
  "bind": "0.0.0.0",
  "obs_url": "ws://127.0.0.1:4455",
  "obs_token": "REPLACE_WITH_GENERATED_OBS_TOKEN",
  "maintenance_token": "REPLACE_WITH_GENERATED_MAINTENANCE_TOKEN",
  "rigs": [
    {
      "id": "rig1",
      "url": "http://ACTUAL_RIG_ADDRESS:48194",
      "management_url": "http://ACTUAL_RIG_ADDRESS:48198",
      "scenes": ["Rig 1", "MEGA PINBALL"]
    }
  ]
}
```

Use one entry at home; add rig2 (or more rigs) with distinct IDs, URLs and scene
mappings as needed. Get each serial path on its rig with
`ls /dev/serial/by-id/` during its local bootstrap. Set display-service and
management API URLs to their actual configured ports. Missing videonode evidence remains
UNKNOWN, never “no consumers.” Videonode itself is installed separately.

```sh
chmod 600 /path/to/stream-config.json
sudo python3 /path/to/software-RELEASE/install_linux.py \
  --bundle /path/to/software-RELEASE --config /path/to/stream-config.json
sudoedit /etc/pinrig-stream.env
```

In the environment file add `OBS_WEBSOCKET_PASSWORD=...` using systemd environment
file quoting for special characters. Enable OBS WebSocket and match its URL and
password. Restart with `sudo systemctl restart pinrig-stream`.

Expected: `systemctl is-active pinrig-stream` returns `active`; open
`http://STREAM_PC_ADDRESS:48195`. Until rigs exist, they appear unreachable.
The setup creates/reuses `pinrigdisplay`, stages a versioned venv under
`/opt/pinrig-stream`, and installs a systemd service. A rerun preserves credentials.
For failure, inspect `journalctl -u pinrig-stream -n 100 --no-pager`, correct the
reported prerequisite/configuration issue, then rerun the installer.

## 3. Bootstrap each rig locally, then update through its API

On each rig, install the Linux prerequisites and copy a matching software bundle.
Create a private rig configuration outside the checkout:

```json
{
  "role": "rig",
  "id": "rig1",
  "serial": "/dev/serial/by-id/ACTUAL_DEVICE",
  "bind": "0.0.0.0",
  "management_port": 48198,
  "obs_token": "SAME_OBS_TOKEN_AS_STREAM_PC",
  "maintenance_token": "SAME_MAINTENANCE_TOKEN_AS_STREAM_PC"
}
```

Use the credentials generated in step 2 and the actual USB path collected on
this rig. Optional local fields include `port`, `videonode_url`, `bootsel_mount`
and `management_bind`. Keep the rig and management ports distinct. Then run,
on that rig:

```sh
chmod 600 /path/to/rig-config.json
sudo python3 /path/to/software-RELEASE/install_linux.py \
  --bundle /path/to/software-RELEASE --config /path/to/rig-config.json
```

Expected: `pinrig-rig` runs the display/booth service; `pinrig-manager` runs the
software-management API, normally on port 48198. Bootstrap creates/reuses the
service account and USB permissions, and installs root-owned management code,
a fixed local installer and `/etc/pinrig-rig.json`. The management API stays
available while the display service restarts. Allow its configured port from
the stream PC. Initial bootstrap is local; an API cannot install itself onto a
blank rig.

Set `management_url` for each rig in the stream configuration. Stage a software
bundle at `/var/lib/pinrig-stream/releases/RELEASE`, readable by `pinrigdisplay`.
Choose the rig and release in the overview, enter the maintenance credential,
and choose **Install rig software**. The overview uploads validated files to the
management API, starts an installation job, follows its progress and verifies
the running rig release. It needs no SSH access, keys or rig OS login.

The rig API accepts a bounded archive of immutable release files and an install
request containing only a release name. It invokes its own trusted installer
with fixed local configuration; it never executes the uploaded installer script.
Application wheels install as `pinrigdisplay`. Management code and the local
helper are updated only by rerunning the trusted local bootstrap. Updates keep
rig configuration, environment and durable receipts; firmware is installed
separately through the rig page.

For a failure, read the management job's phase/error and
`journalctl -u pinrig-manager -n 100 --no-pager` on the rig. Correct the reported
prerequisite, credential, artifact or service problem and retry. Rerunning local
bootstrap preserves the environment credentials and receipt database.

## 4. Install the display (on the rig webpage)

Copy the complete display bundle to `/var/lib/pinrig-host/releases/RELEASE` on
its rig, readable by `pinrigdisplay`. Open the rig page, select the release and
enter its maintenance credential. Installation jobs keep HTTP available while
normal USB delivery and booth commands pause. Uploads use only validated files,
write `main.py` last, reset, then verify firmware identity, actual runtime and
reported display health.

For a Pico without the matching runtime: hold BOOTSEL while connecting USB and
mount its RP2350 volume on the rig. Set `bootsel_mount` in rig configuration to
that mount path and rerun rig setup (or use `--bootsel-mount` for a manual service).
The service user must be able to read/write the mounted volume. Check **Install
bundled runtime** before installation. This copies the bundled UF2, waits for USB
to return, then installs the application. Select the actual persistent USB path;
it must match the Pico after runtime startup. Physical BOOTSEL/mounting is attended.

With an existing matching runtime, leave that checkbox clear. A runtime UF2 alone
is not a complete display installation. **Clean reflash** additionally discards
pending messages and unconfirmed tap receipts; ordinary updates, reconnects and
restarts preserve durable receipt handling. A clean application reflash replaces
the complete managed file set without requiring a backup or old environment.

Expected: job succeeds, versions match and display health is current. With no
fresh source the sign is UNKNOWN; with fresh evidence it resumes the resolved
state. Inspect physical pixels and real touch separately from API status.
For failure, the job reports the phase/error and releases USB ownership. Correct
runtime/USB/mount issues and retry; interrupted jobs are marked failed after a
service restart. Never upload with an unrelated process still owning that USB port.

## Updates

Build and stage a new immutable release. Use the overview for rig software and
the rig page for display firmware; a software update does not implicitly reflash
the display. Software stages before service replacement and refuses to overwrite
an active release with different contents. Retry interrupted setup or install a
new release after correcting the reported error. Firmware and software maintenance
share an installation lock on the rig. Do not update during an event.

Update the stream PC using the same local bootstrap command and its configuration.
Its service is `pinrig-stream`; the legacy `pinrig-obs --rig1/--rig2` sender remains
available but must not run alongside the stream service for the same rigs.

See [operations](operations.md) for failure checks and attended acceptance.
