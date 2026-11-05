# Deployment and acceptance

Assessment: **5 November 2026 — ready for an attended pilot; event acceptance
still pending on both rigs.** No machine is changed by this assessment or by
committing the release.

The software checks pass, and the repository records an earlier Pico USB,
display and real-touch baseline on media-pi. That baseline does not validate
the current firmware changes or the complete two-rig producer deployment.
OBS/videonode interoperability, long-running operation and restart/reconnect
behavior must be checked on the actual installation before unattended use.

## Release evidence

- 111 deterministic unit tests pass on CPython 3.14, with no network, hardware
  or real sleeps. This includes source routing/freshness, UNKNOWN message
  retention on both devices, touch versus cancellation and the Pico renderer's
  UNKNOWN card layout.
- Five simulated minutes of the real host/authority cadence against the Pico
  scheduler pass, including booth messages and cancellations. This protects
  against retry-cache exhaustion at normal publication rates.
- Generated Pico graphics use 1,838,272 bytes on the review machine, within the
  2,000,000-byte budget. Regenerate on the build machine and honor the builder's
  budget check; fonts can affect the size.
- Linux packages are built and checked independently. Hardware imports stay
  outside host/producer installs; OBS dependencies are an optional extra.
- The earlier booth browser check exercised Send and Clear against simulated
  hardware. Physical pixels, taps and installed service behavior require the
  acceptance procedure below.

Two blockers were corrected during review: the Pico still cancelled messages
on UNKNOWN, and its 64-command/120-second retry window could not sustain the
one-second publisher plus host renewals. The Pico now retains messages on
UNKNOWN and advertises a 15-second, 64-command retry window. The Linux device
and HTTP host retain their independent 120-second, 512-command windows.

## Deployment layout

| Machine | Processes | Connections |
| --- | --- | --- |
| Rig 1 Armbian PC | videonode, `pinrig-host`, `pinrig-rig --rig rig1` | Own Pico over USB; own videonode on localhost |
| Rig 2 Armbian PC | videonode, `pinrig-host`, `pinrig-rig --rig rig2` | Own Pico over USB; own videonode on localhost |
| Debian stream PC | OBS, `pinrig-obs` | Local OBS WebSocket; reports to both rig PCs |

The assembled display is **Pico 2 W / RP2350**, not Pi Zero 2 W. Use
[Pico firmware instructions](../firmware/pico/README.md) and the verified
[pinout](../hardware/pinouts.md). The Linux display package remains available
for direct-SPI development; do not install it on a Pico or run the old SPI
service alongside its USB replacement.

Use one state authority and one serial-port owner per rig. `pinrig-host` listens
on localhost:48193. Each booth/OBS ingress listens on the intended LAN interface
at port 48194. Videonode defaults to localhost:8090, OBS to localhost:4455.
Allow the stream PC and booth operators to reach 48194 on the trusted event LAN.
The booth has no login. Do not expose it to the public internet.

Choose actual DNS names or stable LAN addresses for both rigs; `.local` requires
working local name resolution. Confirm the exact OBS scene constants in
`pinrig_producers/obs.py`: `Rig 1`, `Rig 2`, `MEGA PINBALL`.

## Roll out one rig at a time

Keep the other rig on its previous release until the first passes acceptance.
Record the Git revision, device boot session, stable USB path and acceptance
results for each rig. Keep the previous checkout/virtual environment and a
copy of the previous Pico files/assets for rollback. An older UF2 alone does
not back up application files, assets or outstanding acknowledgments.

Run the following from a checkout of the selected revision. Python 3.11+ and
the OS's Python venv support are required on the PCs. Install videonode separately;
this repository does not install or reconfigure it.

### 1. Update the Pico

Stop `pinrig-rig` and `pinrig-host` on the rig PC before using mpremote. Preserve
`interactions.json`; do not erase outstanding acknowledgment receipts. Follow
the Pico README to generate and copy **all** assets and firmware, copying
`main.py` last. This release requires four UNKNOWN assets, including
`unknown-3-0.r`; updating only `core.py` or only the old full-screen image is
insufficient. A working MicroPython installation does not need UF2 reflashing
for this application update.

After reset, check that the device shows the UNKNOWN logo without a rendering
fault and enumerates at its stable `/dev/serial/by-id/...` path. Close mpremote
before starting the host. Keep the existing wiring, SPI speed and USB power
arrangement.

### 2. Install the rig host and booth service

Create the dedicated account if it does not already exist:

```sh
sudo useradd --system --user-group --home-dir /var/lib/pinrig --shell /usr/sbin/nologin pinrig
sudo usermod -aG dialout pinrig
sudo python3 -m venv /opt/pinrig-host
sudo /opt/pinrig-host/bin/python -m pip install ./pinrig_protocol ./pinrig_host ./pinrig_producers
sudo install -m 0644 pinrig-host.service pinrig-rig.service /etc/systemd/system/
```

On upgrades, prepare a new virtual environment and keep the old one for
rollback rather than overwriting the only working installation. The supplied
units use `/opt/pinrig-host`; switch that path to the prepared environment while
services are stopped, or use a service override pointing to its absolute path.

Create `/etc/pinrig-host.env` with the real device path:

```ini
PINRIG_SERIAL=/dev/serial/by-id/YOUR_PICO
PINRIG_BIND=127.0.0.1
```

Create `/etc/pinrig-rig.env`, using `rig2` on the second PC:

```ini
PINRIG_RIG=rig1
PINRIG_RIG_BIND=0.0.0.0
```

Optionally add `VIDEONODE_CREDENTIALS="user:password"` when the local videonode
requires Basic authentication. Optionally set `PINRIG_OBS_TOKEN` to the same
value on both rig services and the stream-PC generator. Store credentials in
these machine-specific files, not in Git or command-line arguments.

```sh
sudo chown root:pinrig /etc/pinrig-host.env /etc/pinrig-rig.env
sudo chmod 0640 /etc/pinrig-host.env /etc/pinrig-rig.env
sudo systemctl daemon-reload
sudo systemctl enable --now pinrig-host pinrig-rig
sudo systemctl status pinrig-host pinrig-rig
```

The host unit creates `/var/lib/pinrig-host` for its durable receipt database.
Keep that directory when upgrading or rolling back. `GET /healthz` only proves
the HTTP process is running. Inspect full status at
`http://RIG_ADDRESS:48194/api/status` and logs with
`journalctl -u pinrig-host -u pinrig-rig -f`.

### 3. Install the OBS generator

On the Debian stream PC, create the same dedicated `pinrig` service account if
needed. Enable OBS's WebSocket v5 server at localhost:4455, then install:

```sh
sudo python3 -m venv /opt/pinrig-producers
sudo /opt/pinrig-producers/bin/python -m pip install ./pinrig_protocol './pinrig_producers[obs]'
sudo install -m 0644 pinrig-obs.service /etc/systemd/system/
```

Create `/etc/pinrig-obs.env` with real addresses and the existing OBS password:

```ini
PINRIG_RIG1_URL=http://RIG_1_ADDRESS:48194
PINRIG_RIG2_URL=http://RIG_2_ADDRESS:48194
OBS_WEBSOCKET_PASSWORD=YOUR_EXISTING_OBS_WEBSOCKET_PASSWORD
```

Add `PINRIG_OBS_TOKEN` if configured on the rigs. Protect the file and start:

```sh
sudo chown root:pinrig /etc/pinrig-obs.env
sudo chmod 0640 /etc/pinrig-obs.env
sudo systemctl daemon-reload
sudo systemctl enable --now pinrig-obs
sudo systemctl status pinrig-obs
```

The generator reconnects if OBS starts later. Inspect
`journalctl -u pinrig-obs -f`. The adapters intentionally use top-level program
scene names; nested visibility, previews and transition frames are not tally
inputs for this release.

## Attended acceptance before event use

Record pass/fail and observed behavior for **each** rig:

1. With OBS reachable and not streaming, disconnect every videonode consumer:
   INACTIVE. Connect a consumer: ACTIVE. Disconnect it: INACTIVE. Leave it idle
   for at least two minutes to exercise initial zero counts and repeated SSE
   resynchronization without unexpected UNKNOWN flashes.
2. Stream with program scene Rig 1, Rig 2 and MEGA PINBALL. Only the corresponding
   rig(s) show ON AIR. A different scene establishes not on air, so videonode
   consumer evidence decides ACTIVE/INACTIVE. Stop streaming and check fallback.
3. Stop OBS/the generator or disconnect its network: each affected rig becomes
   UNKNOWN after source freshness and delivery leases expire. Restore it and
   verify automatic recovery. Confirmed fresh ON AIR must survive loss of only
   videonode; otherwise videonode failure produces UNKNOWN.
4. Send a booth message, queue another, then lose OBS evidence and let the state
   lease expire. Both messages remain. Send another while UNKNOWN. Verify the
   compact unknown logo/caption above the readable message card. Tap the first
   message: acknowledged. Clear the next from the page: cancelled. Restoring
   ACTIVE/ON AIR must preserve the remaining card.
5. Verify a real tap is durably received on the host and confirmed to the Pico;
   check `interaction_delivery`, touch faults, queue status and recent outcomes.
   Acceptance and visible rendering are distinct from a person's acknowledgment.
6. Unplug/replug USB and restart each service, OBS and the Pico. Verify recovery,
   fresh state after reconnect and no replay of old transient messages. A device
   reboot starts UNKNOWN and does not restore message cards; unconfirmed touch
   receipts survive. A host restart waits for fresh producer state.
7. Leave both rigs running for at least 15 minutes with several messages/taps
   and scene/consumer changes. Check for retry-capacity errors, serial timeouts,
   service restarts, render/touch faults and visible corruption. Confirm state
   changes and booth messages remain responsive.

Optional low-level USB smoke test, with an observer at the display: stop
`pinrig-rig`, clear existing cards and run
`python tools/usb_smoke.py --url http://127.0.0.1:48193` from an environment
with the checkout. It deliberately changes signs/messages and checks queueing,
deduplication, expiry and UNKNOWN retention. Restart `pinrig-rig` afterward.
Use `tools/hardware_smoke.py` only for direct-device HTTP/SPI development.
These scripts perform real I/O and sleeps and are excluded from unit discovery.

## Rollback and operating limits

Stop the affected authority and host. Restore the previous environment/service
paths and the matching complete Pico code/assets, preserving the host database
and device outbox. Restart the host, authority and generator and repeat the
basic state/message checks. Never let mpremote and the host own USB together.

If an older firmware predates UNKNOWN message retention or the shorter Pico
retry window, it restores those older limitations too. A source problem can be
isolated by stopping its service; the display will show UNKNOWN and retain booth
messages on this release. The booth page still needs its local rig/USB host to
be reachable to send or clear a message.

Queues and histories are bounded: one visible/three pending messages, eight
unconfirmed device receipts, 16 recent outcomes on Pico, 32 on Linux, and 10,000
durable host receipts. The host receipt store is not automatically pruned; plan
archival before it fills. A full or failed store must be corrected rather than
treated as successful acknowledgment delivery. Wi-Fi control on the Pico and
smooth continuous animation are outside this release.
