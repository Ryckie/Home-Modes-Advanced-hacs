# Companion apps: widgets, shortcuts and scripts

What the Companion apps can do with the Home Modes entities, from the current Companion app
documentation (read on 2026-11-12). "Not listed" means the documentation does not mention it,
not that it does not work.

| Entity | iOS widgets | iOS Siri Shortcuts | Android widgets | Android Device Controls |
| --- | --- | --- | --- | --- |
| `select` (`select.home_mode`) | Shown in the **Sensors** widget (the documented list includes `select` and `input_select`); the **Entities** widget takes any domain | Not mentioned; use *Perform action* | **Entity State** widget shows any entity; changing a select is not described | **Not listed** |
| `binary_sensor` (`binary_sensor.home_mode_<role>`) | Shown in the **Sensors** widget (listed) | Read-only; no action | Entity State widget (any entity) | **Not listed** |
| `switch` (overlays, Auto) | **Entities** widget (any domain; the docs' example shows a switch) | *Control switch* action (switch or input_boolean) | Entity State widget; tap toggles "if supported" | **Listed** (on/off) |
| `script` | **Scripts** widget; *Custom* widget *Run Script* action | *Run Script* action | *Action button* widget performs an action (the page does not list which) | **Listed** ("turn on script") |

The iOS "Actions" widget no longer exists (removed); use the Scripts or Custom widget.

**Not verified:** Android *Action button* widget details for scripts (the page does not name
them), Android quick settings tiles, CarPlay and Apple Watch with scripts, and everything
about exposing these entities to Assist. Nothing here was tested on a phone.

## What this means

Widgets and shortcuts can **show** the mode (select, binary sensors) on both platforms, and
can **change** it most reliably through **scripts** (and, for overlays, switches). So the
practical way to switch modes from a home-screen widget, a Siri phrase or Android Device
Controls is one script per mode that calls `home_modes.set_mode`.

A script that a person starts keeps that person's identity for the actions inside it (a
non-admin user's allow-list still applies). A script started by an automation has no user and
is trusted.

## Copy-paste: one script per mode

Add to `scripts.yaml` (or create the scripts in the UI by switching to YAML mode). Use the
role **ids** in `mode`, never the names:

```yaml
home_mode_home:
  alias: "House mode: Home"
  icon: mdi:home
  sequence:
    - action: home_modes.set_mode
      data:
        mode: home

home_mode_night:
  alias: "House mode: Night"
  icon: mdi:weather-night
  sequence:
    - action: home_modes.set_mode
      data:
        mode: night

home_mode_away:
  alias: "House mode: Away"
  icon: mdi:home-export-outline
  sequence:
    - action: home_modes.set_mode
      data:
        mode: away

home_mode_vacation:
  alias: "House mode: Vacation"
  icon: mdi:palm-tree
  sequence:
    - action: home_modes.set_mode
      data:
        mode: vacation

# Back to the automatic modes (ends a manual override)
home_mode_auto:
  alias: "House mode: Auto"
  icon: mdi:calendar-sync
  sequence:
    - action: home_modes.set_auto
```

For custom modes use `custom_1` ... `custom_10`; for an overlay use `home_modes.set_overlay`
with `overlay: guest` and `active: true` or `false`.

Then:

- **iOS:** Scripts widget (or Custom widget with *Run Script*), or a Shortcut with *Run Script*.
- **Android:** a Device Control for each script (Android 11+, enable the controls in the app's
  settings), or the Action button widget.
- **Show the current mode:** a Sensors/Entities/Entity State widget on `select.home_mode`.

## Should there be per-role button entities? (recommendation, not built)

You asked to evaluate, not build. **Recommendation: no, not for the first release.**

For:
- No YAML for the user; one entity per mode shows up in every picker.
- Pressing a button entity would use the same permission check as the services.
- Button entities are the documented target of the iOS *Press button* shortcut action.

Against:
- The scripts above already reach every surface in the table above (iOS Scripts widget, Custom
  widget, Run Script shortcut, Android Device Controls), and for those the documentation
  confirms support; for button entities it confirms only the iOS shortcut action. Android
  Device Controls and widgets, and Assist exposure, are **unverified** for buttons.
- One extra entity per enabled mode and custom mode (up to about 14) in every device page and
  entity picker, and entity churn whenever a mode is enabled, disabled or added.
- Names: entity names would have to follow role renames, or stay as ids; either choice is
  confusing to someone.
- Assist already has the intent handlers, which need no exposed entity.

I would revisit this if users report that writing the scripts is the obstacle. **Waiting for
your decision**; nothing was added.
