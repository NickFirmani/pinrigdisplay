# Project Guidelines

## Purpose

Production: OBS PC → two independent Armbian tiny PCs → USB → Pico 2 W → SPI → display.
Home testing: this PC → Pi 4B host → USB → Pico 2 W → SPI → display.
The Pico is the display controller; Linux computers are hosts. Keep producer
interpretation separate from firmware and share the command contract. Desktop
artwork tools are build dependencies only. See README.md and docs/deployment.md.

## Python Style

- Write idiomatic Python with clear names and simple control flow.
- Prefer small, cohesive modules with one obvious responsibility.
- Prefer small functions and explicit data flow over hidden global state.
- Use type hints for public APIs and wherever they make behavior clearer.
- Use `pathlib`, context managers, dataclasses, and standard-library facilities
  where they improve clarity.
- Prefer the standard library unless a dependency provides substantial value.
- Keep hardware-specific code behind narrow interfaces so most behavior can be
  developed and tested without a Raspberry Pi or display.
- Separate rendering, application logic, configuration, and hardware I/O.
- Avoid premature abstraction. Introduce shared abstractions only when there is
  a concrete use for them.
- Add concise docstrings to public modules, classes, and functions when their
  purpose or contract is not already obvious from the code.

## Design and Reliability

- Validate inputs at system boundaries and fail with useful error messages.
- Handle resource ownership explicitly. SPI and GPIO resources must be released
  predictably, including when an operation fails.
- Keep side effects at the edges. Prefer pure functions for drawing, layout,
  state transitions, and data conversion.
- Inject clocks, delays, hardware transports, and other external effects when
  doing so makes logic deterministic and testable.
- Use logging for runtime diagnostics; do not scatter ad hoc `print` statements
  through library code.
- Preserve a simple path for running the application locally and on the Pi.
- Do not silently ignore hardware or rendering errors.

## Testing

- Use automated tests for behavior that can be tested without physical hardware.
- Every behavioral change or bug fix must add or update relevant tests.
- Tests must be deterministic, isolated, and useful. They must not depend on
  execution order, wall-clock timing, the network, or attached hardware.
- Test observable behavior and public contracts instead of implementation
  details.
- Favor small fakes or injected dependencies over extensive mocking.
- Keep hardware integration checks separate from the default unit-test suite and
  label them clearly because they require the Raspberry Pi and display.
- Avoid real sleeps in unit tests. Use an injected clock or fake delay function.
- Include edge cases and failure paths where they carry meaningful risk.
- A test should fail for a clear reason when the behavior it protects regresses.

## Change Discipline

- Keep changes focused and reviewable.
- Update documentation when setup, usage, wiring, or behavior changes.
- Run the relevant tests for every change. Run the full test suite before
  considering a feature complete.
- Keep generated files, caches, local environments, secrets, and machine-specific
  configuration out of version control.
- Do not mix unrelated cleanup or broad refactoring into a focused change.
- Maintain compatibility with the Python version installed on the target Pi
  unless the project explicitly changes that requirement.

## Hardware Safety

- Use Pico GP numbering for firmware and BCM numbering for Linux GPIO and document physical-pin
  mappings separately.
- Treat the display connection as write-only unless MISO is explicitly added.
- Do not drive the display backlight directly from a GPIO. Backlight dimming
  requires suitable switching hardware.
- Default to conservative SPI speeds and make faster speeds configurable.
- Never change GPIO assignments, power assumptions, or electrical behavior
  without updating the wiring documentation.
