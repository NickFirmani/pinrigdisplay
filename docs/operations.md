# Operation and diagnostics

Start at the stream overview (default port 48195), then follow a rig link
(default 48194) for display details, booth messages and firmware maintenance.

| Observation | Check/action |
| --- | --- |
| OBS unavailable or authentication error | Open OBS; enable WebSocket; check its URL/password against `/etc/pinrig-stream.env`; restart `pinrig-stream` after changing configuration. |
| Unrecognized scene | Compare the program scene with that rig's configured scene list. Unmapped scenes mean that rig is not live; the overview flags an unrecognized scene. |
| Rig unreachable/stale | Check its power/network/service. Last known status is retained but marked stale; it is not a current health verdict. Other rigs continue independently. |
| USB disconnected/stale display report | Check the selected persistent USB path, cable and competing processes. The rig retries; a cached state is not proof that the display still works. |
| UNKNOWN/source age high | Inspect OBS and videonode availability. Required missing or stale evidence remains UNKNOWN. |
| Display/touch fault | Read the rig error, inspect wiring and physical panel, then retry or reinstall a complete release. Health reports cannot prove pixels or wiring are correct. |
| Tap receipt unavailable/storage failure | Inspect filesystem space/permissions and the rig/Pico fault. A failed durable write must not be presented as successful acknowledgment. |
| Install failed/interrupted | Read job phase/error; resolve API access, prerequisites, USB, BOOTSEL mount or version mismatch, then retry. Clean reflash is available when application state should be discarded. |

`/healthz` means only that the process responds. Keep process running, fresh
source, accepted command, successful render and person acknowledgment distinct.
Reported ages use each machine's own clock, with the overview tracking rig poll
age separately. A stale report never becomes healthy by refreshing the browser.

Logs on Linux:

```sh
sudo journalctl -u pinrig-stream -n 100 --no-pager
sudo journalctl -u pinrig-rig -n 100 --no-pager
sudo journalctl -u pinrig-manager -n 100 --no-pager
```

Maintenance state persists in `/var/lib/pinrig-stream/maintenance.json` and
`/var/lib/pinrig-host/maintenance.json`. Rig software jobs persist separately in
`/var/lib/pinrig-manager/maintenance.json`, so they survive display-service restarts. Rig tap receipts live in
`/var/lib/pinrig-host/interactions.sqlite3`. Credentials belong in the root-readable
`/etc/pinrig-{stream,rig}.env` files and are not returned by status APIs.

## Acceptance

Run `.venv/bin/python -m unittest discover -v` locally. Default tests use fake
hardware, clocks, HTTP and installers; they do not prove physical behavior.

On the home chain, then both production rigs, verify clean setup, installer
reruns, rig update, firmware update, failed/interrupted install and recovery,
version reporting, OBS closed/wrong password/unknown scene, one unreachable rig,
USB unplug/reconnect, stale source, render/touch/storage failures and restart.
Exercise sign states slowly and check pixels and real taps in person. Keep
hardware checks outside the default suite and avoid running them during an event.

For the existing attended API smoke check, pause OBS reporting and ensure no
booth cards are active:

```sh
.venv/bin/python -m tools.usb_smoke --url "$RIG_URL" --rig rig1
```

Set `PINRIG_OBS_TOKEN` to the configured token. The check cancels its own card
and leaves OBS evidence unknown; resume reporting afterward. It does not replace
physical touch/pixel, restart or power-cycle checks.


## Home validation record — 7 November 2026

On the Pi 4B (`admin@media-pi.local`, Python 3.13.5):

- Earlier firmware installation verified `step4-home-1` on MicroPython 1.29.0.
  API-to-USB ON AIR/UNKNOWN, retained messages, Send/Clear and slow checks of all
  four display states passed. Physical pixels/taps remain attended acceptance.
- Local bootstrap installed the revised overview and management API using
  `step4-api-10`. Through the overview's HTTP installation control, a second
  deployment release (`step4-api-11`, same application code) uploaded, installed
  and verified successfully. The management process stayed running across the
  rig restart. No service SSH key was installed.
- The display USB device was absent at final API verification. The rig reports
  that separately as disconnected; the software installation itself succeeded.
  Reconnect the Pico before repeating live display checks. OBS and videonode
  were unavailable and appeared as unknown/unavailable.

Home test links: [overview](http://media-pi.local:48197) and
[rig](http://media-pi.local:48196). Management uses authenticated port 48198.
Production defaults remain unchanged. BOOTSEL copying, physical pixels/taps,
live OBS and both production rigs remain attended acceptance checks.
