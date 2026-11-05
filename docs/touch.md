# XPT2046 touch and booth acknowledgment

This page describes the Linux SPI/touch adapter and shared acknowledgment
semantics. The assembled Pico 2 W uses the same gesture and receipt contract
with a LittleFS outbox instead of SQLite; see
[Pico firmware](../firmware/pico/README.md) and the dated hardware results in
[implementation status](implementation-status.md).

The operator supplied the full Elecrow 4-inch ST7796S/XPT2046 wiring now recorded
in the README. CE1 pressure and coordinate responses were observed during actual
presses on the Pi 4B. The module's XPT2046 touch IC is also listed in the
[Elecrow reference](https://elecrow.com/wiki/4.0_Inch_480320_SPI_TFT_LCD_Module_with_ST7796_DriverWith_Touch_Function.html).

This first interaction is **tap anywhere on the display to dismiss the visible
card**. No coordinate mapping or calibration is claimed. Position-sensitive
buttons will require calibration against this display orientation. No GPIO
outputs, boot overlay or electrical settings were changed for touch. The reader
uses SPI0 CE1 at 100 kHz, independently of the LCD on CE0 at its configured rate.
T_IRQ is connected to BCM23 but is not used by the pressure-polling adapter.
Two consecutive samples debounce each press/release. Pressure thresholds were
checked against actual idle and pressed readings; 12-bit Z1 must exceed 100 and
Z2 must be below 4000, excluding rail readings. Validate these on other panels.

Enable in device TOML only after confirming the documented wiring:

```toml
touch_enabled = true
interaction_path = "/var/lib/display-controller/interactions.sqlite3"
```

The service account needs write access to that directory; the supplied device
unit creates it. The input worker releases its SPI handle on exit. Input failure
turns off acknowledgment capability, reports a touch fault and keeps sign
rendering operational. Restart the service after repairing an input/storage fault.

A booth producer sends `show_message` with `requires_ack: true` and an appropriate
priority. Such cards never time out. They display a tap-to-ack prompt. A gesture
must begin after a released state has been observed and after the card is fully
rendered. Layout changes, expiry, cancellation or replacement invalidate the
press; a release cannot accidentally acknowledge the next card.

On release, the device first commits an interaction to SQLite with synchronous
writes, then removes the card. Entries contain globally unique `interaction_id`,
original `message_id`, original device `session`, and `kind`. Requires-ack cards
record `acknowledged`; timed cards tapped early record `dismissed`. Remote cancel
remains separate and never creates a human interaction. A failed or full outbox
retains the card and renders a visible acknowledgment fault. The outbox holds
eight unconfirmed entries and survives device restart even though cards/states
restart UNKNOWN. Status repeats pending interactions until confirmation.

The serial host uses its own durable SQLite store (default
`/var/lib/pinrig-host/interactions.sqlite3`, configurable with `--interactions`).
It saves and deduplicates each interaction before sending `confirm_interaction`
to the device. Confirmation loss is safe: the same receipt is stored once, then
confirmed again. Host storage is bounded to 10,000 receipts; on capacity/error,
confirmation stops and `interaction_delivery` reports the fault. Export/archive
and retention management beyond that limit remain operator work; no receipt is
automatically deleted. The supplied host unit creates the state directory.

In the current deployment this host module runs inside `pinrig-rig`, whose
single service unit creates the same state directory. Existing receipt data
stays at the path above when migrating from the old separate host service.

When using direct device HTTP without the host, the caller must durably save
receipts from `status`, then confirm each interaction ID. Otherwise eight taps
will fill the outbox by design. A test harness is not a permanently running host.

## Physical verification — 30 October 2026

- Detected changing X/Y and pressure samples on CE1 while the operator touched.
- Displayed persistent `booth-touch-test-1` and received an actual touch
  acknowledgment; the visible card cleared with no touch fault.
- Restarted the device service and verified that exact acknowledgment survived.
- Exercised host receipt storage through a local HTTP delivery adapter; the host
  saved the receipt, confirmed it, and the device removed its outbox entry.
- Unit coverage includes stale/held presses, opening/replacement invalidation,
  timed-dismiss versus ack semantics, persistence and capacity failures,
  unreadable storage, host deduplication and failed host storage.

This validates local SPI touch on the 4B. USB/Zero touch deployment and
coordinate-sensitive controls have not been physically tested.
