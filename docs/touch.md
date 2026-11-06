# XPT2046 touch and booth acknowledgment

The Pico 2 W owns display and touch on one shared SPI bus. Use the
[authoritative wiring table](../hardware/pinouts.md) for Pico GP and physical
pin assignments. The Linux host connects only through USB. Setup and updates
are covered in the [deployment guide](deployment.md).

Touch uses pressure polling at 100 kHz, restoring the LCD SPI speed afterward.
The firmware tests Z1 and Z2; it does not implement calibrated position-sensitive
buttons. Tap anywhere to acknowledge the visible, settled card. The gesture
must begin after a released state has been observed. Layout changes and card
replacement invalidate the gesture, preventing a release from acknowledging a
different card. Physical pressure response requires checking on the actual panel.

Booth cards require acknowledgment and do not expire. A successful tap first
saves a receipt in the Pico's LittleFS `interactions.json` outbox using atomic
replacement and sync, then removes the card. Preserve this file during updates.
The outbox holds eight unconfirmed receipts. A failed or full outbox retains the
card and reports a fault. Remote Clear is cancellation and creates no human
interaction. UNKNOWN and lease expiry preserve cards and allow acknowledgment.

The embedded host in `pinrig-rig` saves and deduplicates receipts in SQLite before
confirming them to the Pico. Its default path is
`/var/lib/pinrig-host/interactions.sqlite3`, configurable with `--interactions`;
`pinrig-rig.service` creates the state directory. Confirmation loss is safe:
the receipt is stored once and confirmed again. Host storage holds 10,000 receipts;
on capacity or storage error confirmation stops and reports a delivery fault.
Receipt export and retention management remain operator work.

See the [firmware contract](../firmware/pico/README.md) and
[command protocol](protocol.md). Unit tests cover device gestures and receipt
handling without hardware. Physical pixels, real taps, power cycles and USB
reconnects still require attended verification on each installation.
