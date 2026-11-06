# Architecture Definition

Production, following the owner's explicit diagram:

```text
OBS PC → two independent [Armbian tiny PC → USB → Pico 2 W → SPI → display]
```

Home testing:

```text
This PC → Pi 4B → USB → Pico 2 W → SPI → display
```

The Pi 4B is still a supported test host. The Pico is the display controller; the Linux computer
is the host. Keep those names distinct. Keep source interpretation on the PCs.
Confirm the OBS PC OS and home source/test method before writing OS-specific
install commands; the existing Debian/systemd instructions are not proof of
the actual stream-PC OS. Do not invent hostnames or require a second home rig.

## 4. Install, reflash, and diagnose without guesswork

Provide a supported release bundle containing matching Pico code/assets and
version information. A user should not assemble a staging directory, discover
hidden imports, or build fonts merely to install the display.

Write one numbered path per machine, with commands labeled by where they run,
the few required values collected once, expected output, and a short recovery
step. Provide separate first-install and update sections. Proposed tooling must
be implemented and tested before instructions present it as available.

| Machine | Required operator workflow |
| --- | --- |
| Pico/display | Connect USB; enter BOOTSEL if needed; install the chosen runtime and complete release; reset; verify UNKNOWN and version. Distinguish a runtime UF2 from a complete application install. |
| Armbian host / home Pi 4B | Install prerequisites and one rig service; select the detected USB device; configure rig identity/source endpoints; start service; open status page. Detect an existing service account so rerunning setup works. |
| OBS PC / home source PC | Enable/configure OBS WebSocket when used; install and start the producer; select one or two host destinations and scene mappings; show connection and delivery status. Use instructions matching its actual OS. |

Make clean reinstallation the recovery path. No mandatory device backup,
receipt migration, or old-environment restoration workflow. Reflashing may
discard pending messages and unconfirmed tap receipts; say this once plainly.
Distinguish that deliberate maintenance reset from ordinary reconnect/restart,
where existing durable receipt guarantees should continue to work. Still stop
the USB-owning host service during uploads and restart it afterward.

Expand the existing booth/status view rather than creating another service:
show OBS connection/authentication status, current program scene and streaming
state, last fresh observation age, per-rig report success, videonode status,
USB connection, installed versions, displayed state, and actionable last error.
Some of these fields require new producer/status data; they are not currently
available just by relabeling the UI. Never display credentials.

Include explicit checks for OBS closed, wrong password, unrecognized scene,
one unreachable rig, USB unplug, stale source, firmware fault, and failed tap
storage. Distinguish process running, source fresh, command accepted, display
rendered, and person acknowledged. Explain where logs live and give one command
to read them on each supported OS.

Documentation target: README about one screen with topology and entry links;
one installation/update guide; one short operation/troubleshooting guide;
one protocol reference; one wiring reference. Link to details instead of
repeating them. Remove obsolete plans after extracting still-needed decisions.

Done when a person can install from a clean machine, update, reflash, and find
the cause of a disconnected display using only the guide. Validate first on
the home chain, then both production rigs. Test installer reruns and failure
messages, producer single/two-destination behavior, and status freshness.
