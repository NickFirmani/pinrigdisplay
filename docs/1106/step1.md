## Architecture Definition

Production, following the owner's explicit diagram:

```text
OBS PC → two independent [Armbian tiny PC → USB → Pico 2 W → SPI → display]
```

Home testing:

```text
This PC → Pi 4B → USB → Pico 2 W → SPI → display
```

## 1. Establish what is dead, then remove it

The Pi 4B is still a supported test host. Its former direct-SPI display role is
a retirement candidate. The Pico is the display controller; the Linux computer
is the host. Keep those names distinct.

Start with this evidence-based inventory. “Candidate” does not mean proven unused.
Check imports, entry points, assets, packaging, tests, docs, and the supported
installation paths before deleting code. Git history is enough for obsolete plans.

| Item | Finding and disposition |
| --- | --- |
| `AGENTS.md` purpose; Zero migration sections in `README.md`, `docs/display-plan.md`, `docs/host-plan.md`, `docs/implementation-status.md` | Stale target architecture. Replace with the two setups above; remove the Zero rollout roadmap. Clarify Pico GP numbering versus Linux BCM numbering. |
| `docs/deployment.md`, `docs/rig-producers.md`, Pico README | Overlapping setup and migration narratives. Consolidate into one current install/update guide. Remove old two-process migration and mandatory backup/restore from the normal path. |
| `media-pi`, `rig1.local`, `rig2.local`, historical machine-specific acceptance claims | Historical evidence/examples, not verified current hosts. Remove from active commands; retain only useful dated measurements outside the quick start. Collect actual addresses during setup. |
| `display_controller/server.py`, `api.py`, `config.py`, `serial.py`, `touch.py`, `display/st7796.py`, `display-controller.service`, `config.toml`, `tools/hardware_smoke.py` | Old Linux display runtime candidates. Retire after extracting the build/preview dependencies and replacing any useful test fixtures. Home USB hosting does not need these SPI drivers. |
| `display_controller/controller.py`, `tests/helpers.py`, Linux-device tests | Linux controller doubles as a test reference/fake today. Migrate relevant host integration coverage to explicit fakes or the Pico core before removing it. Do not keep an entire obsolete product merely as a fixture. |
| `display_controller/display/pages.py`, `renderer.py`, artwork, `preview.py`, `tools/build_pico_assets.py` | Still useful: Pico asset generation imports `PageRenderer`, `_font`, and `encode_rgb565`. Extract the needed desktop build/preview code before removing the Linux package. |
| `pinrig-host.service`, `pinrig_host/server.py`, `pinrig_producers/client.py`, `tools/usb_smoke.py` | Optional maintenance HTTP path; smoke tooling currently uses it. Decide whether to retain one clearly separated diagnostic tool or replace it with direct USB diagnostics, then remove the unused listener/unit/client together. |
| `pinrig_host/service.py`, `delivery.py`, `client.py`; `pinrig_protocol/` | Live production dependencies. `pinrig-rig` imports `Host`, `SerialDelivery`, and `LocalClient`. Keep; the package name does not imply an obsolete extra service. |
| `pinrig_producers/obs.py`, `authority.py`, `rig.py`, `videonode.py`, `booth.html`, rig/OBS units | Live path. Keep two-rig production support. OBS currently requires both destinations; allow one configured destination for home testing. Confirm videonode availability at home without fabricating negative evidence. |
| `docs/event-producer-plan.md`, `docs/touch.md`, `docs/protocol.md`, generated demo GIFs | Preserve current contracts and wiring facts in concise references. Remove superseded roadmap prose and animations that misrepresent the Pico UX. |
| `hardware/pinouts.md` | Current Pico wiring, but repeated tables and C-style constants duplicate the same facts. Keep one authoritative table, shared-bus notes, and connector reference. |

Deliver a short final removal list with a reason per item, followed by focused
deletions. Adjust package metadata, tests, commands, and links in the same change.
Do not treat the existing 116 tests as proof of hardware behavior or dead-code
coverage. The full suite passes locally at this planning baseline.

Done when both supported setups use an explicit, small dependency graph, no
active instructions point to retired machines, and useful test/build behavior
survives the cleanup.