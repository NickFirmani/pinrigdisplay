# Command protocol v1

The authority and USB host module run in one `pinrig-rig` process. Its HTTP
API exposes `/api/status`, `/api/obs`, `/api/messages`, and `/api/clear`;
there is no public `/api/commands` listener.

The command envelope below is shared by the in-process host and Pico USB link.
USB uses newline-delimited UTF-8 JSON at 115200 baud with an 8192-byte frame
limit excluding the newline. Overflow discards through the next newline.
Invalid encoding, JSON, versions, operations and fields receive explicit errors.

```json
{"version":1,"request_id":"unique-id","operation":"hello","params":{}}
```

First call `hello` and retain its `result.session`. Include `session` in every
mutating command. A device or host restart creates a new session, starts UNKNOWN,
and rejects commands addressed to the previous session. `hello` and `status`
need no session. Request IDs are 1–64 ASCII letters, digits, or `_.:-`. Use
unique IDs (UUIDs are suitable), including for lease renewals.

```json
{"version":1,"session":"SESSION_FROM_HELLO","request_id":"state-1","operation":"set_state","params":{"state":"on_air","lease_seconds":15,"valid_for":30}}
```

| Operation | Parameters |
| --- | --- |
| `hello` | None. Returns session, retry window/capacity, acknowledgment capability. |
| `set_state` | `state`: `on_air`, `camera_active`, `camera_inactive`, `unknown`; `lease_seconds`: 1–60, default 15; `valid_for`: 1–300, default 30; `diagnostic`: up to 120 characters. |
| `show_message` | `title`: 1–40 characters; `body`: 1–240; `duration`: 1–300 seconds, default 8; `priority`: integer 0–9, default 0; `requires_ack`: boolean, default false. |
| `cancel_message` | `message_id`, returned by `show_message` (the original request ID). |
| `status` | None. Reports requested/displayed state and revisions, faults, visible/pending/recent message outcomes and touch capability/faults. Host wraps device status with connectivity/freshness information. |
| `confirm_interaction` | `interaction_id`. Idempotently removes a durably received device outbox entry; rejects when touch storage is disabled. |

Text is plain text, retained verbatim. Empty/whitespace-only text and control
characters other than tab/newline are rejected. Overlong content is rejected,
never silently shortened. Layout overflow is visibly ellipsized; message
acceptance returns this text policy. No markup or terminal escapes are rendered.

Success envelopes contain `version`, `request_id`, `ok: true`, and `result`.
Errors contain `ok: false` and `error: {code, message}`. Unparseable framing has a
null request ID. Mutations distinguish `accepted` from `display_success` and
`display_fault`. Accepted rendering failures remain accepted, are reported, and
are retried by the render loop. Query status for the current outcome; a cached
acceptance response is a snapshot, not an ongoing delivery receipt.

## Retry and reconnect contract

The embedded host retain up to 512 mutation responses for
**120 seconds** from first receipt. The Pico device retains 64 for **15 seconds**;
`hello` advertises each endpoint's actual limits. Within that window, the same normalized command/request ID
returns the original response without repeating side effects. Reusing an ID
with different content returns `request_conflict`. Entries are not evicted early;
a full window rejects new work with `retry_capacity`. Read-only hello/status
requests are not cached. Clients must not retry an old transient request after
the endpoint's advertised retry window or across session changes; allocate
globally unique IDs for new work. Host and device windows are independent.

The serial host has one sender, a two-second response deadline and bounded
1–30 second reconnect backoff. It does not automatically replay messages after
uncertain delivery. The host response explicitly reports `delivery_uncertain`,
`device_accepted: null`, and `message_replay: false`; the original message may
already be on the display. Retrying the request returns that cached outcome.
After connectivity returns, query device status by original message ID. Device
history retains the last 16 terminal message outcomes on Pico,
so it is not an audit log.

The host keeps the latest desired state even when disconnected, explicitly
resends it after reconnect, and never queues transient messages for reconnect.
Its command session is independent of the device session. Host restart intentionally
forgets desired state. Producers must submit fresh state again.

## Ownership and freshness

One producer-side authority per rig owns resolved state. The host accepts the
latest command; it does not arbitrate competing sources. `valid_for` tells the
host how long the upstream observation remains current. Renewals do not extend
that deadline. The host renews at one third of the lease, using remaining
freshness; stale/missing evidence sends UNKNOWN. The device expires a command at
`min(lease_seconds, valid_for)`. A duplicate does not renew either deadline.

Stop the rig service before direct USB diagnostics so only one process owns
the serial port.

## Scheduling and outcomes

One visible message and three pending messages are allowed. Higher priority wins;
equal priority is FIFO. A higher-priority arrival drops the visible lower-priority
message permanently. Timers begin after the final fixed card is successfully
rendered. Expiry/cancel selects the next message. UNKNOWN preserves visible and
queued messages and accepts new ones, including after state-lease expiry. It
shows an LCP logo with “Stream Status Unknown” beneath it, shrinking above a
message card when present and filling the screen otherwise; detailed
diagnostics remain in status responses. Touch uses the Pico XPT2046 wiring. Requires-ack messages have no
timed expiry; a fresh press/release after the layout settles records
`acknowledged`. A tap on a timed card records `dismissed`. Remote cancellation
remains `cancelled`. See [touch operation](touch.md). The eight-entry device outbox
survives restart and repeats in status until explicitly confirmed. The host
persists/deduplicates receipts before confirming; a full or failed store does not
confirm. Touch-disabled devices still reject requires-ack messages.

HTTP maps validation to 422, ID/session conflicts to 409, capacity to 429,
unknown message IDs to 404 and unavailable/uncertain delivery to 503. Accepted
commands with rendering faults return 200 and `display_success: false`.
`GET /healthz` reports HTTP process liveness only. Inspect `status` separately
for USB connectivity, display health, source freshness and interaction support.
HTTP connections have a five-second read timeout and at most eight active handlers;
a busy host sender rejects new work rather than building a backlog.

## Rig HTTP message API

POST `/api/messages` accepts `request_id`, `body`, and optional `title`,
`duration`, `priority`, `requires_ack`. With any optional parameter supplied,
USB validation/defaults apply (title required, duration 8 seconds, priority 0,
requires_ack false). Legacy body/request_id-only requests retain title BOOTH,
priority 8 and requires_ack true. IDs need not have a booth prefix.
POST `/api/clear` accepts any valid `message_id`; cancellation is not acknowledgment.
Example: `{"request_id":"notice-1","title":"Notice","body":"Ready","duration":12}`.


## Monitoring and release identity

Protocol `version: 1` identifies the command contract, not a software release.
Pico status includes `firmware` (release, protocol, target, declared runtime and
asset identity) and `runtime_version` (actual runtime major/minor/patch). Unbundled
firmware reports an unknown release. Firmware status retains requested/displayed
state and revisions, render/touch errors and receipt outcomes.

Rig `GET /api/status` adds `status_schema: 1`, `software_version`,
`software_release`, `source_ages`, and `sources` (age, freshness and evidence values) to existing authority/USB status. Embedded
host status includes `device_status_age`, `device_status_stale`, and `maintenance`.
A cached device snapshot remains diagnostic data after disconnect, marked stale.
Ages are local monotonic durations, never timestamps to compare between machines.

Rig `GET /api/releases` lists staged release directories; `GET /api/maintenance`
returns the latest persistent job. `POST /api/firmware` takes `release`, `clean`
and optional `runtime` booleans. Stream `GET /api/status` contains OBS diagnostics,
independently aged rig reports and its latest deployment job. `POST /api/install`
takes configured `rig` and staged software `release`. Maintenance requests require
a configured Bearer maintenance token and reject cross-origin browser requests.
They return an accepted job (202), with phases and final success/error polled via
status. A restarted in-progress job becomes failed, never assumed successful.
No credentials are returned. `/healthz` remains process presence only.


### Rig software management API

The independent `pinrig-manager` service (default port 48198) stays up across
`pinrig-rig` updates. Every route requires the maintenance Bearer credential;
browser requests must be same-origin. The stream configuration supplies each
rig's explicit `management_url`.

| Request | Contract |
| --- | --- |
| `GET /api/health` | Authenticated management schema/process check. |
| `PUT /api/releases/RELEASE` | `application/x-tar`, bounded Content-Length (64 MiB maximum). Regular files only; traversal, links, duplicate paths, unlisted files and checksum failures are rejected. Existing release contents are immutable. |
| `POST /api/install` | JSON `{"release":"RELEASE"}`; returns 202 and a persistent job ID. One installation at a time. |
| `GET /api/maintenance` | Latest persisted job, for recovery after a lost install response or overview restart. |
| `GET /api/jobs/ID` | Returns the matching job's phase, running/succeeded/failed state and result/error. Unknown IDs return 404. |

The rig invokes a fixed root-owned installer and local configuration. Uploaded
installer code is never executed; application packages install as the service
account. Management code upgrades require local bootstrap. Firmware and software
updates share the existing rig installation lock. The overview uploads, starts
the job, polls this API, then verifies the rig's identity and installed release.
