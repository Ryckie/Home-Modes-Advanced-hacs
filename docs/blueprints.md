# Blueprints

Three example blueprints in `blueprints/automation/home_modes/`. They use the **role binary
sensors** (`binary_sensor.home_mode_<role>`), never mode names, so renaming a mode does not
break them (tested in `tests/test_blueprints.py`, including a rename and a reload).

The Marketplace and HACS do not install blueprints. Import with the button, or manually:
Settings → Automations & scenes → Blueprints → Import blueprint → paste the GitHub URL, or copy
the file into `<config>/blueprints/automation/home_modes/`. Requires Home Assistant 2026.10.4 or newer.
The buttons point at the `main` branch of the repository.

## Lights off at night [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Flights_off_at_night.yaml)

Source: `https://github.com/Ryckie/Home-Modes-Advanced-hacs/blob/main/blueprints/automation/home_modes/lights_off_at_night.yaml`

| Input | Default | Meaning |
|---|---|---|
| Night sensor | `binary_sensor.home_mode_night` | the role sensor that starts the run |
| Lights | | target (entities, areas, devices) turned off |
| Transition | 0 | seconds, passed to `light.turn_off` |
| Skip while on | none | optional sensor (for example the Guest role); the lights are left alone while it is on |

Runs only on an `off` → `on` change, so a reload of the integration does not switch lights off again.

## Heating setback in away and vacation [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Fheating_setback_away_vacation.yaml)

Source: `https://github.com/Ryckie/Home-Modes-Advanced-hacs/blob/main/blueprints/automation/home_modes/heating_setback_away_vacation.yaml`

| Input | Default | Meaning |
|---|---|---|
| Away sensor | `binary_sensor.home_mode_away` | |
| Vacation sensor | `binary_sensor.home_mode_vacation` | a missing sensor counts as off |
| Thermostats | | climate entities |
| Setback temperature | 16 | used while Away or Vacation is on |
| Normal temperature | 20 | restored when both are off |
| Settle seconds | 5 | wait after a change so Away → Vacation does not briefly restore the normal temperature |

## Notify on vacation or guest [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Fnotify_vacation_or_guest.yaml)

Source: `https://github.com/Ryckie/Home-Modes-Advanced-hacs/blob/main/blueprints/automation/home_modes/notify_vacation_or_guest.yaml`

| Input | Default | Meaning |
|---|---|---|
| Vacation sensor | `binary_sensor.home_mode_vacation` | |
| Guest sensor | `binary_sensor.home_mode_guest` | |
| Notify actions | | your own action(s); the variables `message` and `what` (`vacation` or `guest`) are available |
| Vacation / guest message | defaults | text for `message` |

This blueprint runs *your* action; it does not use the integration's own notification rules
(see [notifications.md](notifications.md)). The Companion app note in the README applies to what you choose.
