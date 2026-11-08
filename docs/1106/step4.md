# 4. Install, monitor, and diagnose by layer

Execution details and repository gaps: [implementation plan](step4-implementation.md).

Production:

```text
Host/stream PC (OBS) → two independent rig PCs (Armbian) → USB → Pico 2 W → SPI → display
```

Home testing:

```text
This PC (source) → rig PC (Pi 4B) → USB → Pico 2 W → SPI → display
```

Organize implementation and documentation into three layers. Here, **display**
means the Pico controller and attached panel; **rig PC** means its Linux host;
**host/stream PC** means the upstream source/OBS computer. Keep source
interpretation on the PCs and share the command contract with the firmware.
Each PC provides monitoring and installation for the layer below it.

## Display

- Run the firmware, render commands, and report firmware version, displayed
  state, and actionable faults over USB. Keep command acceptance, rendering,
  and person acknowledgement distinct.
- Provide a complete, versioned release with matching runtime, code, and assets.
  Installing must not require building fonts, discovering imports, or assembling
  a staging directory. Distinguish a runtime UF2 from a complete application.
- Provide no webpage or installer of its own. The rig PC owns firmware
  installation and monitoring.

## Rig PC

- Run one rig service that owns USB communication with its display.
- Host a rig webpage showing rig identity and software version, USB connection,
  firmware version and health, displayed state, source freshness, tap-storage
  status, and the last actionable error.
- Install, update, and reflash display firmware from that webpage, with release
  selection, progress, failure details, and post-install version/health checks.
  Explain any physical BOOTSEL action required. Suspend normal USB ownership
  during uploads and restore the service afterward, including on failure.
- Expose versioned health/status information to the host/stream PC, including
  timestamps so it can identify stale reports.
- Support both production Armbian machines and the home Pi 4B. Setup must detect
  an existing service account, select the USB device, collect rig identity and
  source settings once, and support reruns.

## Host/stream PC

- Run the producer and interpret OBS/source state. Support one or more rig
  destinations, with independent connection and delivery status.
- Host the overview webpage, expanding the existing booth/status view. Show
  each rig's reachability, report age, rig software version, display firmware
  version and health, and a link to its rig webpage.
- Show OBS connection/authentication, current program scene, streaming state,
  last fresh observation age, per-rig delivery, videonode status, and actionable
  errors. Never display credentials.
- Provide installation and update controls for rig PC software, with progress,
  failure reporting, and post-install version/health checks. Link to each rig
  webpage for display firmware installation.
- Confirm the actual stream-PC OS and home source/test method before writing
  OS-specific setup instructions. Existing Debian/systemd instructions do not
  establish the stream-PC OS. Do not invent hostnames or require a second home rig.

## Installation and recovery

Provide separate first-install and update paths for each PC, with numbered
steps labeled by where they run, required values collected once, expected
results, and short recovery instructions. Include the initial bootstrap needed
before either webpage is available. Proposed controls and status fields must
be implemented and tested before documentation presents them as available;
some require new producer, rig, and firmware reporting.

Use clean reinstallation as the recovery path. No mandatory backup, receipt
migration, or restoration of old environments. Reflashing may discard pending
messages and unconfirmed tap receipts; ordinary reconnects and restarts must
preserve existing durable receipt guarantees.

For home hardware validation, the Pico is connected to `admin@media-pi.local`.
Old firmware need not be backed up and existing state on that Pi may be cleared.
Exercise display states slowly in a loop.

## Verification and documentation

Distinguish process running, source fresh, command accepted, display rendered,
and person acknowledged. Mark missing or stale reports clearly; a running
service alone does not establish display health.

Check OBS closed, wrong password, unrecognized scene, one unreachable rig,
USB unplug, stale source, firmware fault, failed tap storage, and failed
installation. Explain where logs live and provide one command to read them on
each supported OS.

Keep README to about one screen with topology and entry links. Maintain one
installation/update guide, one short operation/troubleshooting guide, one
protocol reference, and one wiring reference. Link instead of repeating details;
remove obsolete plans after extracting still-needed decisions.

Done when a person can bootstrap clean machines, use the host webpage to
monitor and update rig PCs, use each rig webpage to monitor and reflash its
display, and diagnose a disconnected display using only the guides. Validate
first on the home chain, then both production rigs. Test installer reruns and
failure recovery, single/multiple-destination behavior, version reporting, and
status freshness; run the full test suite before implementation is complete.
