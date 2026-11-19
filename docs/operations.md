# Operation and diagnostics

Start at the stream overview (default port 48195). Each card shows the state
reported by the Pico and when the report was sampled, in your browser's local
time. Old reports are marked stale. Open **Status** for OBS and rig
diagnostics or **Debugging/settings** for display tests and rig software installation.
Select a rig name to open its booth page (default port 48194) for messages and
firmware maintenance. Set a nickname in **Debugging/settings** to show it as
`Nickname (rig1)` on the overview card and in the message picker. Save a blank
nickname to show only the rig ID.

In the home topology, run `pinrig-stream` on the development PC. The Pi 4B runs
only `pinrig-rig` and the independent `pinrig-manager`; it simulates one of the
small production rig hosts rather than the OBS/stream PC.

**Status** starts with Videonode activity and the USB display connection for
each rig, followed by the OBS connection. Idle means Videonode reports zero stream consumers. OBS can
show Connected while streaming is stopped. Detailed diagnostics follow below.

## Display test pane

In the stream overview's **Debugging/settings** tab, apply a display test override to one
rig. Choose ON AIR, CAMERA ACTIVE, CAMERA INACTIVE or UNKNOWN and check the
rig card while observing the physical panel. The rig remains the sole
owner of USB delivery. It reports the active override and its remaining time,
continues collecting OBS and videonode evidence underneath it, and returns to
automatic resolution after 60 seconds or when **Return to automatic** is used.

Test overrides are intentionally transient and are not a substitute for source
integration tests. A rig-service restart also clears them; a lost producer lease
still makes the Pico fall back to UNKNOWN.

## Simulate videonode

To check the rig's videonode connection without installing or running videonode,
run this on the rig from the source checkout. The default address matches the
rig's default `videonode_url` (`http://127.0.0.1:8090`).

```sh
python3 rig/videonode_simulator.py --interval 5
```

The simulator defaults to four streams (`camera1`, `camera2`, `camera3`, and
`combined`) and sends consumer-count events plus heartbeats. Press `i` for all
inactive, `1`–`4` to activate one stream, `a` to cycle automatically, or `m` to
return to manual mode. In auto mode, a state key stops cycling and applies that
manual state. Pass `--streams` to override the stream IDs, or adjust `--host`
and `--port` to match a custom rig configuration. Press `q` to quit. The dashboard
should show the videonode source changing between inactive and active.

## Simulate OBS

On the Stream PC, run this from the source checkout before starting
`pinrig-stream`. The default WebSocket address matches the stream service's
default `obs_url` (`ws://127.0.0.1:4455`).

```sh
python3 stream/obs_simulator.py --scenes "Rig 1,Rig 2,MEGA PINBALL,Intermission" --interval 5
```

This serves the OBS WebSocket v5 handshake and the two status requests used by
PinRig. Press `1`–`4` to select a program scene, `s` to toggle streaming, `a` to
cycle scenes and streaming state automatically, or `m` to return to manual
mode. In auto mode, a state key stops cycling and applies that manual state.
Pass the exact scene names configured for the rigs. Press `q` to quit.

## Simulate Twitch chat

On the Stream PC, run this from the source checkout with its Stream PC config.
It uses the production chat grouping and rig-delivery code, while simulating an
authorized, live channel; it does not connect to Twitch or the running stream
service.

```sh
python3 tools/twitch_simulator.py --config ~/stream-config.json
```

Press `1` for one message, `2` for a three-message same-chatter burst, or `3` to
send messages from two chatters. Press `l` to toggle simulated live/offline,
`n` to select the next rig, `t` to mute/unmute that rig, `a` to cycle message
scenarios automatically, or `m` to return to manual mode. Press `q` to stop.
Each rig must be reachable and report a healthy, idle display for delivery.

## Booth messages

The Stream overview opens to **Message**. Select a rig and enter the message.
The title defaults to BOOTH and **Auto dismiss** defaults to 30 seconds.
Use the slider to set 1–300 seconds, or select **Tap to dismiss** to keep the
message visible until a tap. Use the rig's booth page to see the message queue
or cancel a message.

On the booth page, choose **Physical acknowledgment** for a card that stays
until someone taps it or the booth clears it. Choose **Timed** for a card that expires after its
display interval. Press and release anywhere on a visible card to acknowledge
a required card or dismiss a timed one early. **Clear** cancels a visible or
queued card. UNKNOWN preserves messages and their queue.

## Troubleshooting

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

## Logs

Run the command for the affected service on its Linux PC.

```sh
sudo journalctl -u pinrig-stream -n 100 --no-pager
sudo journalctl -u pinrig-rig -n 100 --no-pager
sudo journalctl -u pinrig-manager -n 100 --no-pager
```

Maintenance state persists in `/var/lib/pinrig-stream/maintenance.json` and
`/var/lib/pinrig-rig/maintenance.json`. Rig software jobs persist separately in
`/var/lib/pinrig-manager/maintenance.json`, so they survive display-service restarts. Rig tap receipts live in
`/var/lib/pinrig-rig/interactions.sqlite3`. If the upstream services require
credentials, store `OBS_WEBSOCKET_PASSWORD` on the stream PC and
`VIDEONODE_CREDENTIALS` on the corresponding rig in their root-readable
`/etc/pinrig-{stream,rig}.env` files.

## Acceptance

Run `.venv/bin/python -m unittest discover -v` locally. Default tests use fake
hardware, clocks, HTTP and installers; they do not prove physical behavior.

On the home chain, then both production rigs, verify clean setup, installer
reruns, rig update, firmware update, failed/interrupted install and recovery,
version reporting, OBS closed/wrong password/unknown scene, one unreachable rig,
USB unplug/reconnect, stale source, render/touch/storage failures and restart.

At the assembled display, record the release, rig, and observations for each check:

- Cycle all four signs slowly at the usual viewing distance. During sustained
  barberpole motion, measure USB command round trips and tap response times,
  compare with idle and card changes, and record render times and bytes written.
  Let the lease expire and check the switch to UNKNOWN.
- Send short and 240-character cards with long words, newlines and unsupported
  characters. Check readability, clipping and ellipsis. Open, replace and clear
  cards while watching for a blank frame. Motion should resume after the last card.
- Queue two cards. Tap a required card, allow a timed card to expire, and tap
  another timed card early. Verify each outcome on the rig page. Repeat with
  UNKNOWN and check that a press held across replacement cannot clear the new card.
- Disconnect USB and power-cycle the Pico with a receipt awaiting confirmation.
  Verify reconnect and receipt delivery. Exercise the physical BOOTSEL install
  and check that the display and touch work afterward.

For the existing attended API smoke check, pause OBS reporting and ensure no
booth cards are active:

```sh
.venv/bin/python -m tools.usb_smoke --url "$RIG_URL" --rig rig1
```

The check cancels its own card and leaves OBS evidence unknown. Resume reporting
afterward. Check physical touch and pixels, restart, and power-cycle separately.

## Home validation record — 7 November 2026

With this PC as the stream host and the Pi 4B (`admin@media-pi.local`, Python
3.13.5) as the rig host:

- Earlier firmware installation verified `step4-home-1` on MicroPython 1.29.0.
  API-to-USB ON AIR/UNKNOWN, retained messages, Send/Clear and slow checks of all
  four display states passed. Physical pixels/taps remain attended acceptance.
- An earlier local bootstrap installed the revised overview on the Pi for API
  validation; that placement is superseded by the home topology above. The
  management API used `step4-api-10`. Through the overview's HTTP installation control, a second
  deployment release (`step4-api-11`, same application code) uploaded, installed
  and verified successfully. The management process stayed running across the
  rig restart. No service SSH key was installed.
- The display USB device was absent at final API verification. The rig reports
  that separately as disconnected; the software installation itself succeeded.
  Reconnect the Pico before repeating live display checks. OBS and videonode
  were unavailable and appeared as unknown/unavailable.

Home test links: [overview on this PC](http://127.0.0.1:48195) and
[rig on the Pi](http://media-pi.local:48196). The Pi management service uses
local-network port 48198.
Production defaults remain unchanged. BOOTSEL copying, physical pixels/taps,
live OBS and both production rigs remain attended acceptance checks.

## Forward Twitch chat to the rig displays

1. Set up the public Twitch app on the stream PC as described in
   [Deployment](deployment.md#twitch-chat-setup).
2. Open the stream dashboard and choose **Debugging/Settings → Twitch chat →
   Connect**. Follow the Twitch link, verify the displayed code, and sign in
   as the channel's broadcaster. Use **Change account** to authorize a
   different broadcaster or **Disconnect** to stop forwarding and remove
   the stream PC's stored credentials.
3. Each configured rig starts with chat enabled. Use the checkbox next to its
   nickname and ID to mute it. Select **Send test card** next to an enabled
   rig to verify routing while the channel is offline. The test still needs
   an approved account and an available display.
4. Check **Status → Twitch chat** for the channel's live state and EventSub
   connection. Each rig's status shows its latest delivery outcome.

Chat follows Twitch's live state independently of OBS and videonode. A card
holds up to three consecutive messages from one viewer and closes after eight
seconds. The newest waiting card replaces the previous one. Booth messages
take priority, and chat received during a booth message is discarded.

For an attended check, go live, send a short burst from two Twitch accounts
and verify the grouping, legibility and eight-second timeout on one display.
Send a booth message while chat is visible, then mute the rig during another
chat card and verify that the card clears.
