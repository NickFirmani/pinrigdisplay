# Step 1 removal record

- Linux display runtime, configuration, systemd unit and hardware smoke tool:
  retired direct-SPI product; both supported setups use Pico USB firmware.
- Linux controller, API, configuration, touch and SPI driver tests: retired
  contracts. Host and booth integration tests now exercise the actual Pico core
  with small in-memory display/storage and serial fakes. Pico tests retain device
  behavior coverage; artwork tests retain conversion/layout coverage.
- Old architecture and rollout prose: replaced with current architecture pointers
  and a single install/update guide. Git retains obsolete plans.
- Generated demo GIFs: continuous Linux animation misrepresented Pico UX.
- Repeated pin tables and C constants: one authoritative wiring table remains.

Preserved artwork, RGB565 conversion and preview under `pinrig_artwork`, with
package metadata and builder imports updated. Host, protocol and producer packages
remain separate. Standalone HTTP server, its service unit and producer HTTP client were removed.
The smoke tool now calls the rig APIs; production embeds Host, SerialDelivery
and LocalClient in pinrig-rig.

Validation: 73 deterministic tests; artwork generation 1,838,272 bytes; desktop
preview generation. No physical hardware or home videonode availability verified.
