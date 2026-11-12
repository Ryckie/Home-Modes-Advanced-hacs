# Community post draft

Draft for the thread
[WTH: why is there no Home Modes?](https://community.home-assistant.io/t/wth-why-is-there-no-home-modes/1033966).
Replace the placeholders and the screenshots before posting.

---

**Home Modes Advanced: a community custom integration, looking for testers**

I built a custom integration that tries one shape of what this thread asks for. It is a
community project, not official in any way, and it is a beta.

**What it is**

- One primary mode (Home, Night, Away, Vacation, up to 10 custom ones) plus overlays
  (Guest, Do not disturb), as `select.home_mode` and one `binary_sensor.home_mode_<role>`
  per mode. Renaming a mode does not break automations that use the sensors or the `mode_id` attribute.
- Auto-rules (presence, night and morning by time or sensors) with fixed priorities, and manual
  overrides that win over them.
- Per-user allow-lists enforced on the server, a guest card, enter and exit actions, an optional
  Alarmo bridge that never disarms by itself, optional vacation lighting simulation, history,
  Assist intents, and an import helper for an existing `input_select`.
- Fully local, no external Python dependencies.

**What is tested**

- About 325 automated tests on Home Assistant 2026.10.4 and 2026.11.1: priorities, overrides,
  restarts, DST and time zone changes, clock jumps, permissions, reload/unload/upgrade/removal.
- Card logic with browserless checks.

**What is not tested**

- A real Alarmo (the bridge was tested against a fake one following its documented interface).
- iOS and Android apps: cards, notification channels, widgets, shortcuts.
- Guest setups with real non-admin accounts.
- Raspberry Pi performance, the Marketplace install path, HACS pre-release display.
- The GitHub workflows have not run yet [update before posting].

**How to install**

- HA 2026.11 and newer: Marketplace → add the repository.
- Older (2026.10.4+): HACS → Custom repositories → `https://github.com/Ryckie/Home-Modes-Advanced`, category Integration, pre-release.

**Feedback I would like**

1. Real Alarmo setups (with and without the Ring keypad blueprint): does the bridge behave, is there any echo?
2. iOS and Android: do the cards, notifications and widgets work as described?
3. Guest setups: does the guest card plus allow-list fit how you use guest accounts?
4. Migration from an existing `input_select`: is the import preview clear and correct?
5. Anything in the priority rules that surprises you.

Please attach the diagnostics download and a debug log to bug reports (the issue template explains how).

Repository: https://github.com/Ryckie/Home-Modes-Advanced
Known limits and security notes are in the README.

---
