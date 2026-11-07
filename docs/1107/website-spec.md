# Booth website plan

One simple page per rig, served by its existing host. Works on phones and desktops.

## Features

- **Rig status:** show the rig name, current state, display connection and any fault.
  Refresh automatically and clearly mark stale or disconnected status.
- **Send a message:** title (40 characters), body (240 characters), and a choice
  between physical acknowledgment or timed dismissal (1–300 seconds).
  Default to BOOTH and acknowledgment. Put priority (0–9, default 8) under
  advanced options. Show character counts and useful validation errors.
- **Manage messages:** show the visible message, queued messages and recent outcomes.
  Allow cancellation of visible or queued messages. Clearly distinguish a physical
  acknowledgment from cancellation, dismissal, expiry or replacement.
- **Reliable feedback:** prevent duplicate submissions, keep drafts after errors,
  and distinguish accepted requests from successful display rendering. Do not
  automatically resend messages after a disconnect.

No card preview. Keep the page readable, keyboard accessible, touch friendly,
and free of external dependencies. Keep test controls off the operator page.

## Implementation

1. Update the composer to send explicit options through the expanded message API.
2. Add message lists and clear status/error feedback. Extend host status with
   bounded message details where needed; label unavailable details honestly.
3. Test the API and page, then verify sending, queuing, cancellation, timed expiry
   and real taps on the display. Include UNKNOWN and disconnected/error cases.

Preserve existing booth clients, priority/FIFO rules and message retention on UNKNOWN.
