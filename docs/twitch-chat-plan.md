# Twitch chat on rig displays

The stream PC follows one Twitch channel. Forward chat when Twitch confirms the channel is live and the destination rig has chat enabled and a healthy, reachable display. OBS scenes, stream output and camera activity are independent of this decision. All changes are on the stream PC and rig PC. The Pico uses its existing display protocol and firmware.

## Setup and configuration

| Location | Proposed change |
| --- | --- |
| Stream PC JSON passed to `--config`; `tools/configure_installation.py` | Add optional `twitch_client_id` for a registered public Twitch app. Existing installations work without Twitch setup. |
| `stream/overview.html`, `stream/overview.py` | Under **Debugging/Settings → Twitch chat**, offer Connect, Change account, Disconnect and Send test card. Connect shows a verification link and code. The approved broadcaster is the single channel. Show its name and one toggle per rig, labeled by nickname and ID. The test card bypasses the live gate only. |
| Stream PC `--state` directory | Store broadcaster ID/login and per-rig toggles in `twitch.json`, keyed by stable rig ID; missing toggles default on. Keep OAuth credentials in a separate owner-only `twitch-auth.json`. Write atomically. Disconnect removes credentials and stops forwarding. |
| New `stream/twitch.py` | Own device authorization, token refresh and one outbound EventSub session for chat and stream online/offline events. Subscribe, then reconcile with Get Streams on startup and after connection loss. Preserve newer events arriving during reconciliation. Pause and discard stale work while live status is unknown. |
| New `stream/chat.py` | Own grouping, expiration and independent per-rig delivery. Keep timing defaults below as named constants. In the **Status** tab show channel live/offline/unknown, chat connection health and each rig’s last delivery outcome. |

## From Twitch event to display card

1. Deduplicate EventSub notification IDs once before fan-out using a bounded, expiring cache. Equal text from different messages is valid. If no rigs qualify, discard immediately.
2. Group consecutive messages by Twitch user ID in arrival order. Flush on speaker change, three messages, or **3 seconds from the first message**. Use the display name as title and join bodies with newlines. Respect the existing 40-character title and 240-character body limits: flush before an addition would overflow, and ellipsize an oversized individual message.
3. Show a card for **8 seconds**, auto-dismiss. Each eligible rig gets the same card ID and at most one waiting candidate in stream PC memory. Newer candidates replace waiting ones; discard anything older than **15 seconds** from its first message. A rig becoming eligible starts with new messages. A slow rig never blocks another.
4. In `rig/server/app.py` and `rig/server/authority.py`, add rig HTTP admission for chat. Under the existing sender lock, check display health and occupancy, then issue the existing `show_message` only if idle. Track the chat request ID and use it for targeted `cancel_message`. Both local and remote booth submissions preempt visible chat under the same lock, even at booth priority zero. Report booth occupancy to the stream PC so it discards waiting chat. Keep chat out of the Pico’s pending queue.
5. On mute, disconnect or stream end, discard pending groups for affected rigs and cancel only their visible chat cards. Recheck eligibility before delivery and serialize sends and cancellation per rig. An unreachable display relies on the card timer. Skip ambiguous HTTP deliveries unless the rig can confirm the same request ID; never replay a backlog.

## Verification

Add fake-clock tests in `tests/test_twitch_chat.py` for duplicate IDs, speaker changes, overflow, freshness, reconnect and independent rig delivery. Extend `tests/test_rig_runtime.py` for booth/chat races and targeted cancellation, and `tests/test_pages.py` for setup and toggle persistence. Update `docs/operations.md` and `docs/deployment.md` with operator setup. Run the full suite, then check a burst on one physical display for legibility.

References: [Twitch chat authorization](https://dev.twitch.tv/docs/chat/authenticating/), [EventSub connection lifecycle](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/), [existing display protocol](protocol.md).
