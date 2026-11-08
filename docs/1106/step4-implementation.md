# Step 4 implementation plan

Implements [the three-layer architecture](step4.md). Repository reconciliation:
7 November 2026, including current uncommitted changes. This is a work plan;
features below are not installation instructions or claims of hardware validation.

## Implementation status (7 November 2026)

The code for phases 1–6 is implemented. The reconciliation table below records
the starting point, not the current feature inventory.

- Display release builder: `tools/build_release.py`; identity in Pico status.
- Status/freshness and maintenance: `pinrig_host/service.py`,
  `pinrig_producers/{identity,authority,maintenance,releases,rig}.py` and the rig page.
- Stream overview, OBS diagnostics and independent rig polling:
  `pinrig_producers/{overview,obs}.py` and `overview.html`.
- Linux bundles/bootstrap and management API deployment:
  `tools/{build_software_release,install_linux}.py` and
  `pinrig_producers/{deployment,manager}.py`. Production stream OS is confirmed Linux.
- Operator instructions: [installation](../deployment.md) and
  [operations](../operations.md); monitoring contracts are in [protocol](../protocol.md).

Validation: 113 hardware-free tests pass. Both pages were checked in desktop and
390-pixel mobile browser layouts. Home Pi bootstrap, software update/rerun,
complete firmware installation/version verification, API-to-USB smoke, all four
sign states at three-second intervals, and overview stale/recovery reporting
passed. Existing receipt-file ownership is repaired without deleting its data;
status polling remains available during USB work.

The revised home overview and management bootstrap use `step4-api-10`; the
API successfully deployed rig application `step4-api-11`. The independent manager
PID stayed unchanged across the rig restart. No service SSH key was installed.
Test ports are 48196 (rig), 48197 (overview), and 48198 (management API), leaving
the unrelated old listener on 48194 intact. These are validation settings.
Earlier display acceptance used firmware `step4-home-1` on MicroPython 1.29.0.
The display USB device was absent at final API verification and is reported as
disconnected, separately from successful software installation.

Remaining acceptance: reconnect the home display for another physical check.
Physical pixels/taps, attended BOOTSEL runtime copying, live production
OBS and both production rigs still require attended/deployment validation.

## Current state and gaps

| Layer | Reuse | Work remaining |
| --- | --- | --- |
| Display | `firmware/pico/core.py` reports requested/displayed state and revision, render/touch faults, messages and receipts. Shared command validation already exists. | Firmware/build identity, runtime and asset identity, compatibility metadata, complete release packaging, verified installation. Protocol `version: 1` is not a firmware version. |
| Rig PC | `pinrig_producers/rig.py` embeds `pinrig_host`, owns USB, ingests OBS, polls videonode, and serves `booth.html` plus `/api/status`. `Host` handles reconnect, freshness and durable receipts. | Rig release identity, explicit observation ages, stale device reporting, maintenance ownership, firmware install jobs and UI, software update mechanism. |
| Host/stream PC | `pinrig_producers/obs.py` connects to OBS and publishes expiring observations to either or both configured rigs. | Overview server/page, retained OBS diagnostics, rig polling, configurable rig list/scene mappings, remote rig install/update orchestration. |
| Deployment | Package separation, artwork builder, manual upload guide, systemd service examples, unit tests and attended `tools/usb_smoke.py`. | Built release artifacts, rerunnable bootstrap, supported OS setup, update/recovery jobs, operation guide. Current service files are examples, not installers. |

The existing booth page belongs to each rig; retain its Send/Clear behavior and
extend it for display maintenance. Reuse its visual/status conventions for the
new host overview. There is currently no host webpage to expand.

Existing `/healthz` reports only process presence. Rig status includes a cached
USB snapshot and a local monotonic response time; neither is sufficient for a
remote display-health verdict. OBS snapshots currently discard scene and stream
details after deriving rig booleans, and delivery failures are only logged.
Rig identity and OBS scene routing currently support `rig1`/`rig2` only.

## Implementation order

### 1. Establish release and status contracts

- Define one release manifest containing release/build identity, component
  versions, supported protocol/runtime, asset identity, file hashes and target
  hardware. Keep wire protocol, status schema and software versions separate.
- Add generated firmware identity to status and rig software identity to rig
  status. Report unknown identity explicitly for older firmware.
- Add bounded diagnostic fields and ages for OBS/video evidence, last device
  response, last successful delivery and last error. Invalidate or clearly mark
  cached display state after disconnect. Preserve acceptance/render/ack distinctions.
- Use local monotonic clocks for expiry and response-relative ages across PCs;
  do not compare raw monotonic timestamps from different machines. The overview
  also ages its own last successful rig poll.
- Extend existing protocol/host/producer tests for old or missing fields,
  malformed status, stale snapshots, disconnect and independent error states.

Exit: both webpages can consume a documented, tested status contract without
inferring firmware health from process presence.

### 2. Build complete releases and a local installation engine

- Package firmware, shared validator, generated assets and identity together;
  build artwork only on the development/release machine. Include the chosen
  runtime artifact and its identity, with first-install BOOTSEL instructions.
- Package matching rig and host software with dependencies/install metadata.
  Verify compatibility and hashes before changing a target; avoid requiring
  artwork tools or manual staging on deployed PCs.
- Implement a small rig-side firmware installer behind an injectable transport.
  Validate a complete bundle, upload entrypoint last, reset, then verify reported
  identity, UNKNOWN state and health. Separate runtime installation from app upload.
- Keep ordinary updates/reconnects receipt-preserving; make destructive clean
  reflash explicit. Report interrupted/partial installs as recovery-required.
- Test bundle completeness, corruption/incompatibility, upload interruption,
  reset/verification failure and rerun recovery with fake transports.

Exit: a complete bundle can be installed by a tested local tool before HTTP or
UI orchestration is added.

### 3. Extend the rig service and webpage

- Add a maintenance coordinator shared by delivery, booth commands and the
  installer. Quiesce delivery and close serial before upload; reject conflicting
  commands with a useful maintenance response. Keep HTTP/status alive and resume
  normal USB ownership after success or failure. Do not stop the HTTP-owning
  service to perform a firmware job hosted by that same service.
- Run bounded background install jobs with IDs, phase/progress, results and
  actionable errors. Persist enough job state to diagnose a service restart;
  allow only one maintenance operation per rig. Physical BOOTSEL remains attended.
- Extend the rig page with health/version/freshness details, release selection,
  firmware install/reflash controls and job progress; preserve message behavior.
- Protect maintenance endpoints with configured credentials and same-origin
  checks. The current optional OBS token and unauthenticated booth controls do
  not authorize software installation. Accept validated release artifacts,
  never browser-supplied shell commands or arbitrary install paths.
- Test concurrent delivery/install requests, interrupted jobs, USB cleanup,
  rejected credentials and UI/API success and failure paths.

Exit: the rig webpage can monitor and install its own display end to end.

### 4. Add the host overview around the existing OBS producer

- Retain structured OBS connection/authentication state, scene, streaming,
  sampling age and per-target report outcome. Keep operational status separate
  from expiring source evidence; do not change UNKNOWN/freshness policy.
- Add one host service with a webpage and rig-status polling alongside the OBS
  worker. Keep polling bounded and independent so one unreachable rig cannot
  suppress the other rigs or stall OBS reporting.
- Replace fixed destination arguments with a validated list of rig identities,
  URLs and scene mappings; retain existing single/two-rig CLI compatibility.
  Remove `rig1`/`rig2` restrictions where needed without weakening target checks.
- Show local OBS diagnostics and each rig's age, software/firmware versions,
  display health, source/delivery state and webpage link. Preserve the last
  known values with an explicit stale/unreachable label.
- Test one, two and additional configured rigs, scene mappings, wrong OBS
  password, OBS closed, malformed reports, partial outage and stale recovery.

Exit: one host page explains the entire chain while each rig remains independent.

### 5. Bootstrap locally and update rig software through its API

- Implement rerunnable Linux rig bootstrap: prerequisites, existing service
  account, USB selection/permissions, configuration, release location, receipt
  directory and service installation. Keep Python 3.11+ and Pi 4B support.
- Bootstrap a narrow rig management API locally. Keep its root-owned runtime
  and fixed installer independent of the display service, so software jobs stay
  observable across service restarts. Configure each rig's `management_url` on
  the stream PC; the overview has no rig OS credentials.
- Upload bounded, validated release archives, request installation by release
  name, poll persisted jobs and verify the running rig's release. Never execute
  uploaded installer scripts or accept arbitrary commands/configuration. Install
  application wheels as the service account. Upgrade management code through
  trusted local bootstrap.
- Stage and validate a release before stopping the rig service, switch the
  installed release, restart and verify software identity plus health. Preserve
  config/receipts on ordinary updates; surface recovery instructions on failure.
  Limit elevated operations to installation/service management.
- Add host-page install/update controls and progress using the same job model
  as firmware installation. A rig software update must not implicitly reflash
  firmware; report incompatibility and the required next action.
- Confirm the stream-PC OS before implementing its bootstrap, service startup
  and log commands. Core deployment logic should remain OS-independent.
- Test fresh install, existing account, rerun, missing permissions/dependencies,
  unreachable/unauthorized management API, service/restart failure, version mismatch and recovery.

Exit: after local bootstrap, the host can update a rig through its API and link to its firmware controls.

### 6. Document and validate the complete operator path

- Replace manual staging in `docs/deployment.md` with tested first-install and
  update paths for all three layers. Explain the bootstrap sequence: install
  host tools → bootstrap each rig locally → open rig page → install display firmware.
- Correct README's current rig-hosted booth description to explain both pages;
  add one short operation/troubleshooting guide and update protocol references.
  Reconcile existing receipt-preservation wording with explicit clean reflash.
- Run the full unit suite after behavioral changes, plus targeted contract,
  installer, runtime and page checks. No network, real sleeps or attached
  hardware in default tests.
- Validate on the home chain using `admin@media-pi.local`, then both production
  rigs. Exercise slow display-state loops, real taps, clean installation, both
  update types, unplug/reconnect and the architecture plan's failure cases.
  Keep attended hardware checks separate from automated tests.

Exit: a clean-machine operator can install, monitor, update and diagnose the
chain using only the published guides. Record actual OS/hardware validation;
unverified production steps remain explicitly pending.

## Scope discipline

Keep `pinrig_host` as the embedded USB library; do not rename it merely because
operator documentation now uses “host” for the stream PC. Keep source policy on
PCs, hardware I/O on the Pico, and desktop artwork outside runtime installs.
Build contracts and local tools first, then expose them through existing service
boundaries. Keep display-layout work in step 3 separate from this work.
