# Event producer integration plan

Implementation tracking: [current status](implementation-status.md) and
[implemented protocol](protocol.md). The roadmap below includes deferred hardware
and external-source work.

The first OBS/videonode/booth implementation is documented in
[rig producers](rig-producers.md). It uses two Armbian rig PCs and a Debian stream
PC, with the explicitly agreed top-level scene mapping rather than scene-graph
analysis. Nested visibility and transition analysis below remain future work.

Proposed work, separate from the display device and USB host packages. Producers
interpret external systems and send explicit commands to the
[Pi 4B HTTP host](host-plan.md). The [display device](display-plan.md) receives
only state signs and generic messages.

## Ownership

Keep OBS, videonode, Twitch, booth tools, game detection, and player selection
in separate adapters/processes as needed. They may run on the 4B or another
computer; they communicate with the host through HTTP. UI validation can proceed
without any of these integrations.

Resolve competing source reports in one producer-side authority per rig before
publishing state. The host transports the result; the device does not receive
scene graphs, consumer facts, or source-specific state reducers.

## Camera state production

- Map source identities and actual compositions to the correct rig. An active
  stream involving another rig must not mark this display ON AIR.
- OBS live status requires both an active output and this rig contributing to
  its program composition. Account for nested scenes, visibility, transitions,
  and multiple outputs. A selected scene or preview alone does not prove live use.
- Local-use evidence can include preview, recording that includes this rig,
  and videonode consumers. Merely running OBS does not establish camera use.
- Evaluate source freshness independently. A healthy host/USB connection cannot
  make stale OBS evidence current. Missing evidence is not a negative result.
- Publish ON AIR for confirmed live contribution; otherwise UNKNOWN when live
  status cannot be established; otherwise CAMERA ACTIVE for confirmed local use;
  otherwise UNKNOWN if required local-use evidence is missing; otherwise
  CAMERA INACTIVE. Define required sources explicitly.
- Consider a short producer-side debounce before lowering a confirmed state.
  UNKNOWN should take effect promptly. Send a fresh resolved state after recovery.

Keep reasons, observation times, manual overrides, rig mappings, and detailed
source diagnostics here. The display reports the requested state; it does not
claim independent verification of viewer receipt or privacy.

## Generic message production

Translate source events into title, message text, duration, requires-ack, and
priority. The device does not distinguish chat, booth, player, or game schemas.

| Producer | Initial presentation policy |
| --- | --- |
| Booth tool | High-priority message; request human acknowledgment only when the device supports it. |
| Player selection | Short player announcement; replace stale upstream selections before submission. |
| Game detection/selection | Short game announcement; stabilize automatic detections before submission. |
| Twitch | Moderated, low-priority plain-text message intended for this rig. |

Choose exact durations/priorities in producer configuration. Honor the device's
three-pending-message limit and explicit rejection responses. Drop stale notices
before submission and avoid building an unbounded upstream backlog.

Keep game/player context and selection origin outside the device. Manual
selection takes precedence over automatic detection until explicitly cleared
or replaced. Do not invent default identities for unknown values.

Track acceptance, display, expiry/cancellation, and human acknowledgment as
different outcomes. Operator tools may cancel a message, but must not describe
cancellation or successful delivery as a person acknowledging it. Associate
late acknowledgments with the original message ID.

## Delivery and tests

First validate the display and host with synthetic commands. Add producers
incrementally, beginning with one well-defined source observation contract.
Document required sources, per-rig mappings, freshness limits, and who owns the
resolved state before enabling automatic commands.

Test source-to-rig routing, preview versus program, recording-only and local-only
use, transitions, multiple outputs, conflicting/stale reports, source recovery,
manual override precedence, moderation, and message overload. Use recorded or
fake source observations and injected clocks. Keep external-service integration
checks separate from the default unit suite and device installation.
