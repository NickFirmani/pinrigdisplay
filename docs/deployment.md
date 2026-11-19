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

From the workstation checkout, refresh the source on the Linux host. This
exports working-tree changes and new, non-ignored source files. It creates the
destination on first use. Later runs replace exported files and remove files
that a previous refresh exported and the workstation has since removed.
Files outside the export, such as the host's build venv, stay in place.

```sh
tools/copy-source.sh admin@media-pi
```

The host needs SSH, `tar`, and Python 3.11 or newer. It can receive the source
even when it has no internet access. Log in with `ssh admin@media-pi` and run
the role commands from `~/pinrig`. Pass a different destination directory name
as the second argument if needed. On the first refresh of an older copy, stale
files from before source tracking was added may still be present.

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
| Stream | `stream/installation/status.sh` | `stream/installation/install.sh RELEASE` | `stream/installation/test.sh` |
| Rig | `rig/installation/status.sh` | `rig/installation/install.sh RELEASE` | `rig/installation/test.sh` |

The release name resolves to `~/<role>-RELEASE`, the default output of
`build.sh`. If `~/<role>-config.json` is missing, the installer guides you
through creating it and saves it with mode 0600. Allocate a terminal with
`ssh -t` when running this remotely.

PinRig HTTP services accept requests without application credentials on the
sealed, trusted LAN.

Subsequent runs reuse the saved JSON. You can also pass a bundle directory and
config path explicitly. Non-interactive runs require an existing config.
The installer prompts for sudo as needed. Use a bundle built from this source
for the guided install. When updating existing hosts, install the new rig
release on each rig before updating the stream PC.

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

Copy the stream bundle onto the OBS PC and run `stream/installation/install.sh RELEASE`.
The first-run prompts ask for the OBS WebSocket URL, each rig's dashboard and
management URLs, and its scene mappings. For scripted installation, an example
of the saved JSON follows.

```json
{
  "role": "stream",
  "bind": "0.0.0.0",
  "obs_url": "ws://127.0.0.1:4455",
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
sudoedit /etc/pinrig-stream.env
```

If OBS WebSocket authentication is enabled, put its password in
`OBS_WEBSOCKET_PASSWORD` in this file, using systemd environment file quoting for
special characters. Enable OBS WebSocket, match its URL, and restart with
`sudo systemctl restart pinrig-stream`.

Run `stream/installation/test.sh --local-only` and open
`http://STREAM_PC_ADDRESS:48195`. Until rigs exist, they appear unreachable.
The setup creates/reuses `pinrigdisplay`, stages a versioned venv under
`/opt/pinrig-stream`, and installs a systemd service. A rerun preserves the OBS credential.
For failure, inspect `journalctl -u pinrig-stream -n 100 --no-pager`, correct the
reported prerequisite/configuration issue, then rerun the installer.

## Run the stream app locally

From the checkout on a development computer, run:

```sh
cd stream
./install.sh
./run.sh
```

The first run prompts for OBS and rig settings and saves them to
`~/stream-config.json`. The app listens on `127.0.0.1:48195`; open
`http://127.0.0.1:48195`. Pass a config path as the first argument to `run.sh`
to use a different file. The local runner uses the checkout directly, so source
changes take effect on the next restart.

On macOS, `stream/installation/install.sh RELEASE` is also accepted as a
shortcut to prepare this local environment; the release name is not used on
macOS. A Linux release install still validates and installs the named bundle
through the Linux service installer.

For home testing, the development PC is the stream PC and `media-pi` is the rig
host. Do not also run `pinrig-stream` on `media-pi`; one stream authority should
report OBS evidence for the configured rigs. The Pi continues to run
`pinrig-rig` and `pinrig-manager` independently.

## 2. Install the rig service on each Linux host

On each rig, copy its matching bundle, connect the Pico, and run
`rig/installation/install.sh RELEASE`. The first-run prompts ask for the rig
ID and offer available persistent USB serial paths. For scripted installation,
an example of the saved JSON follows.

```json
{
  "role": "rig",
  "id": "rig1",
  "serial": "/dev/serial/by-id/ACTUAL_DEVICE",
  "bind": "0.0.0.0",
  "management_port": 48198
}
```

Optional local fields include `port`, `videonode_url`, `bootsel_mount`
and `management_bind`. Keep the rig and management ports distinct.
After installation, run:

```sh
rig/installation/test.sh
```

If a previous PinRig system service for the same role occupies the configured
port, the installer stops it before starting the replacement and disables the
superseded unit. This includes named instances such as `pinrig-host-display2.service`.
On a bind conflict it uses `ss` from `iproute2` to identify the listener.
If an unrelated or unidentified process owns the port, the installer reports
the conflict so you can choose another port or free it yourself.

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

The stream bundle can also be built directly on macOS: its dependencies are
pure Python, and the builder rejects platform-specific wheels. By default it
writes to `build/stream-RELEASE`. Rig bundles still need a matching Linux host
because they include hardware-oriented dependencies.

The stream role can also be built on macOS because its dependencies are pure
Python. Its builder rejects any platform-specific wheel. The rig bundle still
needs a matching Linux host because it includes hardware dependencies.

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
ssh -t operator@rig2 '~/pinrig/rig/installation/install.sh 20261119.1'
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
