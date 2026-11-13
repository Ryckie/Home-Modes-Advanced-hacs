# Vacation simulation

Switches **selected lights** on and off in the evening so the house looks occupied. Off by
default. Configure → More → Vacation lights.

It runs only while the primary mode is one of the selected modes (default: Vacation) and the
feature is enabled.

## Strategies

- **random**: evening window (start/end, same day), shortest and longest time a light stays on,
  and the shortest gap between switching on. Every light gets its own schedule each day.
- **replay**: copies the on/off times of the **same weekday last week** (7 days earlier, same
  local time even across daylight saving) for the selected lights from the recorder history. If
  the recorder is not set up, the query fails, or no selected light was on that day, it logs a
  warning ("using the random strategy instead") and uses random. The recorder is **not** a
  dependency.

## Rules it follows

- Only the selected lights are touched.
- It remembers which lights *it* switched on. A selected light that is already on (for example
  you turned it on yourself) is left alone, and is not switched off by the simulation.
- When the mode ends, or the integration is unloaded, the lights it switched on are switched
  off.
- State is stored with absolute timestamps. After a restart it continues the plan; if Home
  Assistant was down past a switch-off time, the light is switched off right after startup.
- Quiet: no notifications. The history gets one `vacation_sim_start` and one
  `vacation_sim_stop` system entry (see [history.md](history.md)).
- A day's plan is created when the simulation starts and again after local midnight.
- If switching a light fails, a warning is logged and the simulation continues.

## Limits

- The window must start and end on the same day (end after start).
- Replay needs a recorder that keeps at least 7 days (the default is 10).
