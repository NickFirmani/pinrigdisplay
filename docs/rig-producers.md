# Rig event generators and booth pages

Each of the two Armbian tiny PCs owns its rig's state and USB display. The
Debian stream PC reports OBS observations to both. The tiny PCs replace the
Pi 4B's host role. The assembled USB device is a Pico 2 W, using the firmware in
[firmware/pico](../firmware/pico/README.md); it does not need a Linux USB gadget.
See [deployment and acceptance](deployment.md) for the current rollout order.

```text
Debian stream PC: OBS → pinrig-obs ──HTTP──┬→ rig1 pinrig-rig
                                       └→ rig2 pinrig-rig

Each Armbian rig PC:
  local videonode SSE → pinrig-rig authority → local pinrig-host → USB → display
  local booth page   → generic message/clear ↗
```

## State policy

| Evidence for this rig | Resolved state |
| --- | --- |
| OBS streaming and program scene matches this rig or MEGA PINBALL | ON AIR |
| OBS confirms not on air, and any videonode stream has consumers | ACTIVE |
| OBS confirms not on air, and every videonode stream has zero consumers | INACTIVE |
| OBS evidence missing/expired, or required consumer evidence missing | UNKNOWN |

Confirmed ON AIR wins even if videonode is unavailable. OBS recording, preview,
nested visibility, and transitions are intentionally not interpreted. A different
top-level scene confirms not on air under this deployment's scene convention.
Both rigs can be on air simultaneously. Exact scene constants live in
`pinrig_producers/obs.py`: `RIG_1_SCENE = 'Rig 1'`, `RIG_2_SCENE = 'Rig 2'`,
`BOTH_RIGS_SCENE = 'MEGA PINBALL'`. Internal device state names remain
`on_air`, `camera_active`, `camera_inactive`, `unknown`.

The OBS generator polls v5 `GetStreamStatus` and `GetCurrentProgramScene` every
second, then sends an independent report to each rig. Startup/reconnect always
queries OBS again; it does not trust cached events. OBS reports last at most
8 seconds and are stamped using the receiving rig's monotonic clock. Publishing
to one unreachable rig does not prevent trying the other; HTTP calls time out
after 2 seconds. Reports already older than 8 seconds are dropped. Requests and
network latency can make a switch take several seconds; this is a status sign,
not frame-accurate tally.

Videonode is read locally through `GET /api/streams` and `/api/events` SSE.
`entity` events with `type: stream.consumers` and `payload.total` establish usage
across RTSP, WebRTC and SRT. A running encoder does not establish usage. All
streams on the rig's videonode instance belong to that rig. Zero configured
streams means no consumers. Missing counts mean unknown, not zero.

Videonode emits initial consumer counts when a subscriber connects. Idle counts
are retained while the connection sends heartbeats (normally every 15 seconds).
The adapter reconnects after 20 seconds on the next frame to obtain a full
snapshot because SSE is best-effort and has no replay. Connection failures
immediately invalidate consumer evidence. No evidence is kept fresh beyond
30 seconds without a relevant consumer/lifecycle event or heartbeat. A planned
resync retains the previous observation only within that freshness window.
Reconnects pause for 2 seconds so videonode's once-per-second subscriber-count
poll can observe the departure and re-emit idle zero counts on the next join.

The authority republishes every second with a 3-second lease and validity.
If the rig service stops, the host/device falls back to UNKNOWN instead of
continually renewing the last sign. The USB host remains source-agnostic and
is the only normal writer to the device. Do not run a second authority for a rig.

## Run on each Armbian rig PC

Requires Python 3.11+. Install into the host environment, with no rendering or
OBS dependencies on these machines:

```sh
python -m pip install ./pinrig_protocol ./pinrig_host ./pinrig_producers
pinrig-host --serial /dev/serial/by-id/YOUR_DEVICE --bind 127.0.0.1
# In another terminal (use rig2 on the other PC):
pinrig-rig --rig rig1 --bind 0.0.0.0
```

Open `http://RIG_HOSTNAME:48194/` for that rig's booth page. The default CLI bind
is loopback; a LAN bind is needed for the stream PC and remote booth operators.
The USB host stays on loopback port 48193. Videonode defaults to localhost:8090.
Use `--host-url`, `--videonode-url`, `--bind` and `--port` for other addresses.

The booth page accepts up to 240 characters, with fixed title BOOTH and priority
8. Messages require acknowledgment and remain until a fresh tap or web Clear.
Enable the device's verified touch setup first; the device rejects a message
when touch acknowledgment is unavailable rather than silently making it expire.
Clear means cancelled, not human acknowledgment. The page lists queued, opening,
visible and recent terminal outcomes from device status, and shows USB/display/
touch faults separately. It does not claim a device acceptance means the text
has already appeared. Delivery uncertainty retains the attempted message ID in
the tab so the operator can check/clear it before sending again. Transient
messages are never automatically replayed after failures. The existing
one-visible/three-pending queue applies; terminal history is bounded to 32
outcomes on Linux or 16 on Pico.
UNKNOWN changes only the state sign. Visible and queued booth messages are
retained, and new messages can be sent while status is unknown. The unknown
logo and caption shrink above the message card, using the normal layout.

Optional environment settings:

- `VIDEONODE_CREDENTIALS=user:password` for videonode HTTP Basic authentication.
- `PINRIG_OBS_TOKEN` shared with the stream PC to protect OBS report ingress.

Booth access follows videonode's local-network model. There is no booth login;
use the intended trusted LAN/interface and restrict network access accordingly.
Cross-origin browser writes are rejected; the server does not enable CORS.
Keep tokens and passwords in installation-specific environment files outside Git.

For automatic startup, install `pinrig-rig.service` alongside `pinrig-host.service`
using the existing dedicated `pinrig` account and `/opt/pinrig-host` environment.
Create `/etc/pinrig-rig.env`:

```ini
PINRIG_RIG=rig1
PINRIG_RIG_BIND=0.0.0.0
```

Use `rig2` on the other rig. Add the optional credential/token variables to
this file when needed. Protect it from other users. Then run
`systemctl daemon-reload` and `systemctl enable --now pinrig-host pinrig-rig`.
Inspect `journalctl -u pinrig-rig -f`. The host's existing durable interaction
store must remain enabled to receive/confirm taps.

## Run on the Debian stream PC

Enable OBS's v5 WebSocket server on loopback port 4455. Put its password in
`OBS_WEBSOCKET_PASSWORD`; keep it out of command-line arguments.

```sh
python -m pip install ./pinrig_protocol './pinrig_producers[obs]'
pinrig-obs --rig1 http://rig1.local:48194 --rig2 http://rig2.local:48194
```

`--obs-url` overrides `ws://127.0.0.1:4455`. Set the same `PINRIG_OBS_TOKEN` as
on the rig services if using token protection. Only this optional OBS extra
installs `websocket-client`; the rig and device installations do not need it.

For automatic startup, create `/opt/pinrig-producers` as a virtual environment,
install protocol and the producer OBS extra there, and install `pinrig-obs.service`.
Use a dedicated `pinrig` account and `/etc/pinrig-obs.env` containing:

```ini
PINRIG_RIG1_URL=http://rig1.local:48194
PINRIG_RIG2_URL=http://rig2.local:48194
OBS_WEBSOCKET_PASSWORD=YOUR_OBS_WEBSOCKET_PASSWORD
```

Add `PINRIG_OBS_TOKEN` if configured. Restrict the file's permissions. Run
`systemctl daemon-reload` and `systemctl enable --now pinrig-obs` and inspect
`journalctl -u pinrig-obs -f`. OBS may start later; the generator reconnects.

## Integration contracts and validation

- `POST /api/obs`: exactly `rig`, `live` (boolean or null), `valid_for` (positive,
  at most 8 seconds). Wrong-rig reports are rejected. Optional Bearer token.
- `POST /api/messages`: `body`, `request_id` (a unique protocol identifier
  beginning `booth-`). The same ID/content has the existing bounded host/device
  deduplication semantics; do not replay uncertain deliveries later.
- `POST /api/clear`: `message_id` beginning `booth-`. Only cancels booth messages.
- `GET /api/status`: rig, resolved state/reason, last state-delivery result and
  host/device status. `GET /healthz`: process liveness only.

Automated tests use fake clocks, recorded-shape payloads, in-memory HTTP requests
and fake OBS sockets; no network, hardware or real sleeps. Run the full suite:
`python -m unittest discover -v`.

Before enabling at an event, separately verify the installed videonode version's
SSE schema and initial zero-count snapshot, actual OBS names/authentication,
both rigs in MEGA PINBALL, stopping OBS/streaming, consumer joins/leaves,
network loss/recovery, USB unplug/replug, and booth tap/clear. Local automated
checks do not establish physical display or live-service interoperability.

Upstream contracts inspected for this implementation:
[videonode consumer publication](https://github.com/smazurov/videonode/blob/main/main.go),
[consumer payload](https://github.com/smazurov/videonode/blob/main/internal/streaming/sse_payloads.go),
[SSE endpoint](https://github.com/smazurov/videonode/blob/main/internal/api/events.go),
[OBS WebSocket v5 protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).
