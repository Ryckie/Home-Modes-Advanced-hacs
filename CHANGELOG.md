# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/). Versions below 1.0.0 are betas.

## [Unreleased]

### Fixed

- Alarmo bridge: when Alarmo refuses to arm after its exit delay (open sensors), it puts the
  previous state back before it reports the failure. Home Modes took that revert as a keypad
  disarm and switched to the disarmed mode (usually Home) without reporting anything. The
  revert is now recognised, the mode stays, and one `failed_to_arm` bridge error is recorded.
- A refused change by an allow-list user is now a validation error (HTTP 400) instead of a
  server error (HTTP 500), so Home Assistant no longer logs "Error during service call" for
  every refused tap. The message and the `home_modes_denied` event are unchanged.

### Documentation

- With the default override (*Next auto-rule trigger*), the next automatic trigger also ends
  an override started at the Alarmo panel or keypad, and the startup evaluation after a restart
  counts as a trigger. The Alarmo docs and test scripts said otherwise; corrected.

### Changed

- Options: every screen is saved as soon as it is submitted (the integration reloads), so
  closing the dialog never loses earlier changes. "Save and close" is now "Done". Confirming
  an input_select import no longer discards other edits of the same session.
- Options: every picker (mode, user, rule, notification event) offers "« Back (change
  nothing)"; an empty custom mode name or input_select also goes back.
- Options: User permissions is split into picking the user and editing the rule, which now
  starts from the stored rule. Administrators are no longer listed (they are always
  unrestricted).
- Options: a new notification rule asks for the event first; the mode field only appears for
  "Mode changed to".
- Options: Alarmo mapping rows are saved one by one, only show the switches that matter for
  the chosen direction, and the titles show the step (for example 2/6).
- Options: disabled modes are no longer offered for actions, notifications, vacation
  simulation and user permissions.
- Options: entity pickers are filtered: motion sensors (motion, occupancy, presence),
  charging sensors (charging/plug binary sensors and Companion app sensors) and sleep
  sensors (binary sensors and input booleans).
- Options: "Manual only" can no longer be combined with other night or morning methods.

## [0.9.1] - 2026-11-13

Second beta (pre-release). The first tag to publish; 0.9.0 was never published.

### Fixed

- An expired override could stay in the stored state when a presence timer and the temporary
  expiry fell due together. It is now dropped on every change.

### Changed

- Warning logs of failing notifications, templates and vacation lights now carry only the error
  type, never its text; action errors are cut to 200 characters.
- CI uses the latest Python 3.14 patch (3.14.2 itself fails one recorder test).
- Repository links point to `https://github.com/Ryckie/Home-Modes-Advanced-hacs`
  (the integration is still called Home Modes Advanced).

### Added

- One-click "add to HACS" button, smoke test script, publishing guide, final audit with
  automated reference checks, and more safety tests (log privacy, Alarmo code, echo guard).
- The icon and logo in `brand/` are **placeholders** and will be replaced before 1.0.

## [0.9.0] - 2026-11-12

First public beta. Fully local, no external Python dependencies.

### Added

- One primary mode (Home, Night, Away, Vacation, up to 10 custom modes, plus the derived
  All home and All away signals) and stackable overlays (Guest, Do not disturb), exposed as
  `select.home_mode`, one `binary_sensor.home_mode_<role>` per role, overlay switches,
  `switch.home_mode_auto`, and the since / previous / trigger reason sensors.
- Server-side permissions per user (allow-list or unrestricted); administrators and calls without a
  user are trusted.
- Auto-rules: presence (away delay, vacation after N hours), night and morning methods (time window,
  sleep sensors, phone charging, motion, alarm), fixed priority ranks, manual overrides
  (`next_auto`, `end_of_day`, `duration`, `set_auto`), temporary modes and revert. Timers survive restarts.
- Services: `set_mode`, `set_overlay`, `revert`, `set_temporary`, `set_auto`, `clear_history`,
  `import_input_select`. Events: `home_modes_changed`, `home_modes_denied`.
- Enter and exit actions per role with timeout, failure isolation and loop protection.
- Optional Alarmo bridge (off by default) with loop guard; never disarms unless a mapping explicitly allows it.
- Optional vacation simulation (random or replay), notifications with Companion app channels
  (`HM_ModeChanges`, `HM_Alerts`, `HM_Guests`), history log with logbook entries.
- Dashboard cards (full card and guest card), Assist intents, `input_select` migration helper with
  optional one-way mirror (and optional overlay mirroring), diagnostics download.
- Three example blueprints: lights off at night, heating setback in away and vacation, notify on
  vacation or guest.
- Documentation, manual test checklist, GitHub workflows (hassfest, HACS, lint, tests).

### Known limits

- The icon and logo in `brand/` are **placeholders** and will be replaced before 1.0.
- Beta: not yet tested with a real Alarmo, on real iOS and Android devices, or on a Raspberry Pi.
- The import flow, default role names and Assist replies are English only.
- Home Assistant has no per-service permissions for non-admin users; see the security notes in the README.
