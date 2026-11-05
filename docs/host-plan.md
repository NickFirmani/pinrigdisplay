# Pi 4B host service plan

Deployment update: the two Armbian rig PCs now take the Pi 4B host role, each
connected to a Pico 2 W over USB. This plan retains the original hardware
roadmap; use [deployment and acceptance](deployment.md) for the current setup.
The `pinrig_host` transport now runs inside `pinrig-rig`; production needs one
rig service, not separate host and authority processes. The standalone HTTP
host is retained for maintenance and direct-command development.

Implementation tracking: [current status](implementation-status.md) and
[implemented protocol](protocol.md). The roadmap below includes deferred hardware
and external-source work.

Proposed work. See the [display plan](display-plan.md) for the shared command
contract and the [producer plan](event-producer-plan.md) for source integrations.

## Role and deployment

After the display moves to the Pi Zero 2 W, the 4B remains the host:

```text
Other producers → HTTP on Pi 4B → USB serial → Zero 2 W display service
```

Keep this service small and independently installable. It accepts explicit
state/message instructions from other processes, validates them, routes them
to the device, and reports delivery and device health. It does not need SPI/GPIO
libraries or OBS/Twitch clients. Use the same device command models as the
current direct-SPI development path.

During UI development, a local delivery adapter calls the controller on the 4B.
Later, a serial adapter sends the equivalent commands to the Zero 2 W. Keep the
HTTP contract stable across that change and keep source interpretation outside
both adapters.

## HTTP and USB delivery

- Expose HTTP operations for state, generic messages, cancellation, and status,
  mapping to the device contract without inventing source-specific commands.
- Use a stable USB device identity and a data-capable cable connected to the
  Zero 2 W's USB data port. Document power ownership before installation.
- Correlate USB requests and responses by ID. Bound pending work and timeouts,
  reconnect with bounded backoff, and expose disconnection explicitly.
- Separate host acceptance, device acceptance, display success, and human
  acknowledgment. HTTP responses and status must make the distinction clear.
- On reconnect or device restart, send the latest valid desired state. Do not
  accumulate/replay stale transient messages while disconnected.
- Renew the device state lease while connected. If upstream state is stale,
  send UNKNOWN rather than continually renewing an obsolete sign.
- Store device interactions durably and deduplicate by interaction ID before
  confirming receipt. Leave producer/operator notification to its integration.

Use a single ordered sender per device. Keep retry policy consistent with the
bounded device deduplication window; surface uncertain delivery rather than
silently replaying messages beyond it. Bound HTTP bodies and queues and return
useful errors for invalid input, capacity limits, and unavailable devices.

## State ownership and monitoring

The normal production command writer is this host. Producers must provide
explicit state and freshness information under a documented ownership policy;
conflicting sources are resolved by the producer layer, not by the display.
Optional direct device HTTP is useful for testing and independent Wi-Fi use.
During a direct-control test, stop host state renewal so it does not overwrite
the test command; the latest accepted command otherwise wins.

Run as a dedicated `systemd` service with automatic startup/restart, appropriate
serial permissions, configuration outside the code, and logs in the journal.
Report HTTP process health, USB connectivity, last device response, display
faults, and acknowledgment delivery separately. Bind HTTP intentionally for its
callers and configure access controls for the deployment.

Test with fake serial and local adapters: shared contract parity, unplug/replug,
boot ordering, host/device restart, timeouts, retries, queue overflow, stale
state, rendering errors, and interaction confirmation loss. Unit tests require
no network, hardware, or real sleeps. Verify the installed service and actual
USB connection separately on the 4B and Zero 2 W.
