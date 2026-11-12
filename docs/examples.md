# Copy-paste examples

All examples use **role ids**. Do not use the select state string in automations you want to
survive renaming: the select options are the role *names*, so renaming a role changes the state
string. The `role` and `mode_id` attributes and the binary sensors never change.

## Condition: a role is active (binary sensor, rename-proof)

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.home_mode_night
    state: "on"
```

## Condition on the select attribute (rename-proof)

```yaml
condition:
  - condition: state
    entity_id: select.home_mode
    attribute: mode_id
    state: night
```

For custom modes use the id, for example `mode_id: custom_1`. `role` holds the role type
(`custom` for every custom mode).

## Trigger: the mode changed (state trigger on the select)

```yaml
trigger:
  - trigger: state
    entity_id: select.home_mode
    attribute: mode_id
    to: vacation
```

A state trigger on `binary_sensor.home_mode_vacation` with `to: "on"` works the same way.

## Trigger: event with source and rule

```yaml
trigger:
  - trigger: event
    event_type: home_modes_changed
    event_data:
      kind: primary
      to: away
      source: presence
condition:
  - condition: template
    value_template: "{{ trigger.event.data.user_id is none }}"
```

Overlay changes have `kind: overlay`, `role: guest` and `active: true|false`.

## Trigger on the select, using the role id (rename-proof)

Shown above with `attribute: mode_id`. If you do trigger on the select **state** instead, the
value is the role *name* and changes when you rename the mode:

```yaml
trigger:
  - trigger: state
    entity_id: select.home_mode
    to: "Night"        # breaks if you rename Night
```

## Blueprints

Details of the inputs: [blueprints.md](blueprints.md). The Marketplace and HACS do not install blueprints, so import them with one click or by hand.

| Blueprint | What it does | Import |
|---|---|---|
| Lights off at night | Turns lights off when the Night role becomes active; optional guard while a guest overlay is on. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Flights_off_at_night.yaml) |
| Heating setback in away and vacation | Lowers thermostats while Away or Vacation is active, restores the normal temperature when both end. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Fheating_setback_away_vacation.yaml) |
| Notify on vacation or guest | Runs your own notify action when Vacation starts or the Guest overlay turns on. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Fnotify_vacation_or_guest.yaml) |

Manual import: Settings → Automations & scenes → Blueprints → Import blueprint, then paste the
GitHub URL of the file (`https://github.com/Ryckie/Home-Modes-Advanced-hacs/blob/main/blueprints/automation/home_modes/<file>`). Or copy the file into
`<config>/blueprints/automation/home_modes/`. All three use the role binary sensors, so renaming a
mode does not break them. Every blueprint needs Home Assistant 2026.10.4 or newer.

## Template conditions that survive renames

```yaml
condition:
  - condition: template
    value_template: >
      {{ state_attr('select.home_mode', 'mode_id') in ['away', 'vacation'] }}
```

The same with a binary sensor (an overlay such as Guest is a role too):

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.home_mode_guest
    state: "on"
```

## Trigger when an overlay turns on or off

```yaml
trigger:
  - trigger: event
    event_type: home_modes_changed
    event_data:
      kind: overlay
      role: guest
      active: true
```

## Who or what caused the change

```yaml
condition:
  - condition: template
    value_template: "{{ trigger.event.data.source == 'presence' }}"
```

`source` is one of `manual`, `schedule`, `sensor`, `presence`, `alarmo`, `temporary_expiry`, `system`.
See [priority-and-overrides.md](priority-and-overrides.md) for the ranks.

More examples, including replacing an old `input_select`: [migration.md](migration.md).
