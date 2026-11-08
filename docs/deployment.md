# Install and update

Start with a Linux software bundle for each PC's architecture and Python version,
and a Pico 2 W display bundle. To make these from source, see
[Build releases](#build-releases). On each Linux PC install Python 3.11 or newer,
venv support and systemd. Each rig also needs the `dialout` group.

Use the actual rig addresses, stable USB device paths and OBS program scene names.
Production has two Armbian rigs. At home, configure just the Pi 4B rig.

## 1. Install the stream overview on the Linux OBS PC

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

Add a second rig entry for production with its own ID, URLs and scene names.
Install videonode separately on each rig that supplies camera usage information.

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

## 2. Install the rig service on each Linux host

On each rig, copy the matching Linux bundle and run `ls /dev/serial/by-id/`
to find the Pico’s persistent USB path.
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

Use the credentials generated in step 1 and the actual USB path collected on
this rig. Optional local fields include `port`, `videonode_url`, `bootsel_mount`
and `management_bind`. Keep the rig and management ports distinct. Then run,
on that rig:

```sh
chmod 600 /path/to/rig-config.json
sudo python3 /path/to/software-RELEASE/install_linux.py \
  --bundle /path/to/software-RELEASE --config /path/to/rig-config.json
```

Check `systemctl is-active pinrig-rig pinrig-manager`. Both should return
`active`. Open the rig page at `http://ACTUAL_RIG_ADDRESS:48194`, then check
that the stream overview can reach this rig. Allow the stream PC to reach the
management API on the configured port (default 48198). For a startup failure,
see the [log commands](operations.md#logs).

## 3. Install the display from the rig page

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

1. **Update rig software first when moving to the trimmed display bundle.**
   Older rig software rejects the eight-image bundle because it expects 32
   additional sign images. Stage the matching Linux bundle at
   `/var/lib/pinrig-stream/releases/RELEASE` on the stream PC, readable by
   `pinrigdisplay`. In the overview select the rig and release, enter the
   maintenance credential, and choose **Install rig software**. Wait for the
   verified release and healthy rig service.
2. Stage the display bundle on that rig and follow step 3. The job reports
   its phase and any error. Correct the reported issue before retrying.
3. To update the rig management service or its trusted installer, rerun the
   local bootstrap from step 2. Ordinary updates preserve configuration and receipts.

Update the stream PC using the same local bootstrap command and its configuration.
Its service is `pinrig-stream`; the legacy `pinrig-obs --rig1/--rig2` sender remains
available but must not run alongside the stream service for the same rigs.

See [operations](operations.md) for failure checks and attended acceptance.

## Build releases

Build Linux bundles on the target Linux architecture and Python version. The
build downloads wheels so the installer can use them offline.

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
