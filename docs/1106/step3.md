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

## 3. Rework message presentation

Use two stable layouts: full sign, and compact sign above a fixed message card.
Start with immediate appearance/disappearance. Remove smooth scaling/fading as
a requirement; there is no need to simulate smooth animation in four large jumps.
Compose the final regions without first erasing the message area with a full
background image. Avoid redrawing an unchanged sign when replacing card text.

Use physical examples: short message, 240-character booth message, long word,
newlines, unsupported characters, acknowledgment prompt, queue replacement,
UNKNOWN plus message, and touch/storage failure. Check wrapping (currently
character-based), clipping, line spacing, contrast, and reading distance.
Keep the acknowledgment instruction from consuming the entire title line.

Preserve priority/FIFO rules, cancellation versus acknowledgment, message
retention on UNKNOWN, and fresh press/release binding. Start timed duration
after the final card is successfully drawn. Update the protocol wording and
tests when removing transition timing. A failed render must not report visible
success or consume the reading interval.

Done when opening/closing/replacing cards has no visible blank intermediate
screen, the state remains readable, and a real tap works during normal use.
Add regression tests for lifecycle, geometry, layout boundaries, and errors;
use an attended test for physical pixels and touch.