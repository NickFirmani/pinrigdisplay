# Deployment

Start with a stream bundle for the OBS PC, a rig bundle for each rig PC's
architecture and Python version, and a Pico 2 W display bundle. To make these from source, see
[Build releases](#build-releases). On each Linux PC install Python 3.11 or newer,
venv support and systemd. Each rig also needs the `dialout` group.

Use the actual rig addresses, stable USB device paths and OBS program scene names.
Production has two Armbian rigs. At home, configure just the Pi 4B rig.

## Get the source and prepare for offline installation

On an online machine with GitHub SSH access, clone the repository:

```sh
git clone git@github.com:NickFirmani/pinrigdisplay.git
```

### Copy the source over SSH without Git on the target

From the workstation checkout, send the source to a new directory on the Linux
host. This exports files from the working tree, including local source changes
and new, non-ignored files in the listed project paths. Keep host configs outside
the checkout and copy them separately. Substitute the actual SSH destination and
use a fresh destination directory for each source snapshot.

```sh
tools/copy-source.sh admin@media-pi
```

The host needs SSH and `tar`. It can receive the source even when it has no
internet access. Log in with `ssh admin@media-pi` and run the role commands
from `~/pinrig`. Pass a new directory name as the second argument to copy
another snapshot.

### Prepare the Linux hosts

Before leaving for the venue, provision each host with systemd, Python 3.11 or
newer and working venv support (on Debian-based hosts, install `python3-venv`).
Set up OBS on the stream PC and videonode on the rigs that use it. Build the
role bundles ahead of time using a Linux machine with the same architecture and
Python version as each target. Use [Build releases](#build-releases).

Transfer the source, the complete role bundle directories, and the private host
configuration files over SSH/SCP or on removable media. With removable media,
copy the source onto the host. The bundle and config can stay on the mounted
drive. The install commands use local wheels. The status and test commands use
the installed services and, for full tests, their connections on the venue LAN
and over USB. Internet access is needed during preparation only.

Run these commands from the checkout on the corresponding host:

| Role | Inspect | Install or reinstall | Test |
| --- | --- | --- | --- |
| Stream | `stream/installation/status.sh` | `stream/installation/install.sh BUNDLE CONFIG` | `stream/installation/test.sh` |
| Rig | `rig/installation/status.sh` | `rig/installation/install.sh BUNDLE CONFIG` | `rig/installation/test.sh` |

`BUNDLE` is a role bundle directory containing `software.json` and `wheels/`.
`CONFIG` is the host's JSON file. The installer prompts for sudo as needed.
Status reports systemd state, installed and running releases, and connected
dependencies. Tests exit nonzero on failure. Add `--local-only` to either test
to verify the local service and release before connecting the rest of the setup.
The full stream test needs OBS WebSocket and a fresh status and OBS delivery
for each configured rig. The full rig test also checks that the Pico currently
reports a healthy display over USB. Check physical rendering and touch separately.

## Provision displays at home

Build one display release for both Picos. While BOOTSEL is accessible, hold the
button as you plug each Pico into the workstation and copy the release's
`runtime.uf2` onto the BOOTSEL volume. The Pico reboots into MicroPython. Do this
for a blank Pico or when changing MicroPython versions.

From the repository root, install the app and assets over USB. Use the exact
serial device shown by `connect list`, selecting one Pico at a time:

```sh
.venv/bin/python -m pip install mpremote
.venv/bin/python -m mpremote connect list
.venv/bin/python -m tools.install_display --bundle /tmp/display-RELEASE --port /dev/cu.usbmodem12301
```

On Linux, use the Pico's `/dev/serial/by-id/...` path where available. Close serial
monitors and disconnect the Pico from the rig before provisioning. The command
validates the bundle, uploads its application files and assets with `main.py`
last, resets the Pico, and checks the release, MicroPython version, and display
health over USB.

Power-cycle and label both assembled displays. With the home rig, check the
four sign states and confirm a tap acknowledgment on the rig page. Record the
release and free filesystem space before packing. To check free space, run
`.venv/bin/python -m mpremote connect YOUR_PORT df + reset` with the Pico back
on the workstation. For venue setup, connect each display to its rig and check
that the rig dashboard shows the expected release and a healthy display.

## 1. Install the stream overview on the Linux OBS PC

Copy the stream bundle onto the OBS PC. Create a private configuration
file outside the checkout. Generate one credential with
`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` for OBS reports;
substitute it into this JSON:

```json
{
  "role": "stream",
  "bind": "0.0.0.0",
  "obs_url": "ws://127.0.0.1:4455",
  "obs_token": "REPLACE_WITH_GENERATED_OBS_TOKEN",
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
stream/installation/install.sh /path/to/stream-RELEASE /path/to/stream-config.json
sudoedit /etc/pinrig-stream.env
```

In the environment file add `OBS_WEBSOCKET_PASSWORD=...` using systemd environment
file quoting for special characters. Enable OBS WebSocket and match its URL and
password. Restart with `sudo systemctl restart pinrig-stream`.

Run `stream/installation/test.sh --local-only` and open
`http://STREAM_PC_ADDRESS:48195`. Until rigs exist, they appear unreachable.
The setup creates/reuses `pinrigdisplay`, stages a versioned venv under
`/opt/pinrig-stream`, and installs a systemd service. A rerun preserves the OBS credential.
For failure, inspect `journalctl -u pinrig-stream -n 100 --no-pager`, correct the
reported prerequisite/configuration issue, then rerun the installer.

For home testing, the development PC is the stream PC and `media-pi` is the rig
host. Do not also run `pinrig-stream` on `media-pi`; one stream authority should
report OBS evidence for the configured rigs. The Pi continues to run
`pinrig-rig` and `pinrig-manager` independently.

## 2. Install the rig service on each Linux host

On each rig, copy its matching rig bundle and run `ls /dev/serial/by-id/`
to find the Pico’s persistent USB path.
Create a private rig configuration outside the checkout:

```json
{
  "role": "rig",
  "id": "rig1",
  "serial": "/dev/serial/by-id/ACTUAL_DEVICE",
  "bind": "0.0.0.0",
  "management_port": 48198,
  "obs_token": "SAME_OBS_TOKEN_AS_STREAM_PC"
}
```

Use the OBS credential generated in step 1 and the actual USB path collected on
this rig. Optional local fields include `port`, `videonode_url`, `bootsel_mount`
and `management_bind`. Keep the rig and management ports distinct. Then run,
on that rig:

```sh
chmod 600 /path/to/rig-config.json
rig/installation/install.sh /path/to/rig-RELEASE /path/to/rig-config.json
rig/installation/test.sh
```

Open the rig page at `http://ACTUAL_RIG_ADDRESS:48194`. Once all rigs are set up,
run `stream/installation/test.sh` on the stream PC. Allow the stream PC to reach the
management API on the configured port (default 48198). For a startup failure,
see the [log commands](operations.md#logs).

## Display recovery from the rig page

Copy the complete display bundle to `/var/lib/pinrig-rig/releases/RELEASE` on
its rig, readable by `pinrigdisplay`. Open the rig page and select the release.
Installation jobs keep HTTP available while
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

## Install a new release

For rig software, stage a rig bundle in
`/var/lib/pinrig-stream/releases/RELEASE` on the stream PC and make it readable by
`pinrigdisplay`. In the overview select the rig and release, choose **Install
rig software**, and wait for the rig service to report the new release. The
independent rig manager handles this installation. To install a new manager or
trusted installer, run the local rig bootstrap from step 2.

For the Pico, use the workstation command or follow
[Display recovery from the rig page](#display-recovery-from-the-rig-page).
For the stream service, use the local bootstrap from step 1 with a new stream bundle.

See [operations](operations.md) for diagnostics.

## Build releases

### Linux bundles over SSH

SSH into the target while it has package-index access, or use an online Linux
builder with the same userspace architecture, distribution, and Python
major/minor version. Build one bundle per role and target platform. Two matching
rigs can use the same rig bundle with their own config files. The build downloads
wheels so installation can run fully offline.

From the workstation, run the matching build script over SSH. Choose a new
release name for each distinct build. The script creates the build venv if
needed and writes the bundle to the remote home directory.

```sh
ssh admin@media-pi '~/pinrig/rig/installation/build.sh 20261119.1'
ssh operator@stream-pc '~/pinrig/stream/installation/build.sh 20261119.1'
```

If you built on the target, use the resulting directory directly with
`install.sh`. Otherwise run these from the workstation to relay the whole
bundle to the offline target over SSH:

```sh
tools/copy-bundle.sh admin@media-pi operator@rig2 rig 20261119.1
```

On the receiving rig, with its private config in the home directory:

```sh
ssh -t operator@rig2 '~/pinrig/rig/installation/install.sh ~/rig-20261119.1 ~/rig-config.json'
ssh operator@rig2 '~/pinrig/rig/installation/test.sh --local-only'
```

### Pico bundle

Build the Pico assets and bundle separately on the workstation:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m tools.build_release --output /tmp/display-RELEASE --release RELEASE \
  --runtime /path/to/pico2w.uf2 --runtime-version 1.29.0
```

Choose an immutable release name, such as a date plus revision; each output
must be a new directory. Use the [official Pico 2 W MicroPython runtime](https://micropython.org/download/RPI_PICO2_W/)
matching `--runtime-version`. A display release includes its UF2, application,
shared USB validator and layout, all static/motion graphics, fonts, identity and checksums.
Pillow/fonts are build dependencies only. Keep release directories out of Git.
Hashes detect damaged payloads; stage releases only from a trusted build source.

Expected: role-specific software wheels, a standalone installer, and
`software.json`; display `manifest.json`,
`runtime.uf2`, firmware and `assets/`. Both builders fail on missing build inputs.
If a build fails, remove that incomplete output directory and rebuild.
