# Configuration, services and events

## Roles and ids

All logic, services, events and automations use **role ids**, never display names. The ids are
`home`, `night`, `away`, `vacation`, `all_home`, `all_away`, `guest`, `dnd` and `custom_1` ...
`custom_10`.

- Default role names are stored in English when the integration is set up. You can rename any
  role in the options.
- `select.home_mode` uses the role **names** as its options, so **renaming a role changes the
  select state string**. Use the `role` / `mode_id` attributes (or the binary sensors) in
  automations if you rename modes.
- Names must be unique (case-insensitive).
- Presets: **Simple** enables Home, Night, Away, Vacation. **Extended** additionally enables
  All home, All away, Guest and Do not disturb.

## Entities

| Entity                                  | Notes                                                                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `select.home_mode`                      | Primary mode. Attributes: `role` (role type, e.g. `custom`), `mode_id` (e.g. `custom_1`), `overlays`, `since`, `auto`, `override` (`null` or `{mode, until}`), `temporary` (`null` or `{until, revert_to, revert_to_name}`) |
| `binary_sensor.home_mode_<role id>`     | Per enabled role. Attributes: `role`, `mode_id`; derived roles also `selected`                    |
| `sensor.home_mode_since`                | When the primary mode was set                                                                     |
| `sensor.home_mode_previous`             | Previous primary mode (attribute `role`)                                                          |
| `sensor.home_mode_trigger_reason`       | Source of the last primary change; attribute `rule` holds the rule name                           |
| `switch.home_mode_auto`                 | Auto-rules on/off                                                                                 |
| `switch.home_mode_overlay_<role id>`    | Overlay toggles. Attributes: `mode_id`, `role`                                                     |

Rule names (attribute `rule`, event field `rule`): `night_time_window`, `night_sleep_sensor`,
`night_phone_charging`, `morning_time`, `morning_motion`, `morning_alarm`, `presence_away`,
`presence_all_away`, `presence_vacation`, `presence_arrival`, `presence_all_home`,
`presence_all_home_end`, `temporary`, `temporary_expiry`, `revert`, `role_disabled`, `initial`.

## Options

Settings → Devices & services → Home Modes Advanced → Configure:

Every screen is saved (and the integration reloaded) as soon as you submit it, so closing the
dialog never loses earlier changes. Screens that ask you to pick a mode, user or rule first
offer **« Back (change nothing)** to return to the menu. **Done** closes the options.

- Rename or enable/disable a mode, change the order, add/remove custom modes.
- **Presence and away timers:** persons, away delay (minutes, default 4), vacation after
  (hours, default 24).
- **Night methods** and **Morning methods:** see [priority-and-overrides.md](priority-and-overrides.md).
- **Manual override:** `next_auto` (default), `end_of_day`, `duration` (with minutes),
  `set_auto`.
- **User permissions (guests):** pick a Home Assistant user (admins are not listed: they are
  always unrestricted), then *Unrestricted* or *Allow-list* and the allowed modes. The next
  screen starts from the user's current rule; users without a rule are unrestricted. Permissions are enforced server-side.
- **Integrations** (sub-menu):
  - **Enter and exit actions**: per mode, overlay or custom mode, plus the timeout per action
    (default 30 s). See below.
  - **Alarmo bridge**: [alarmo-and-ring-blueprint.md](alarmo-and-ring-blueprint.md).
  - **Vacation simulation**: [vacation-simulation.md](vacation-simulation.md).
  - **Notifications**: [notifications.md](notifications.md).
  - **History log**: [history.md](history.md).
  - **Import from input_select**: [migration.md](migration.md).

## Enter and exit actions

Every mode, overlay and custom mode can have *exit actions* (run before the mode changes, when
the mode is left or the overlay is switched off) and *enter actions* (run after the change, when
the mode becomes active or the overlay is switched on). They use the normal Home Assistant
action editor.

- Each action runs as its own script, in order, with a context whose `parent_id` is the context
  of the change, so traces and the logbook link them to the change.
- A failing action is logged and recorded in the history entry (`action_failures`); the other
  actions still run and the mode change is never blocked or reverted.
- Each action has a timeout (default 30 s, options → Integrations → Enter and exit actions). A
  slow action is stopped, reported as a timeout, and the change goes on.
- Variables available in templates (same names as in notifications): `from_role`, `to_role`
  (role ids), `from_mode`, `to_mode` (aliases, always ids), `from_name`, `to_name`, `role`,
  `role_name`, `phase` (`enter` or `exit`), `source`, `rule`, `user_id`. `from` is reserved in
  Jinja and not available. Use ids for logic; names are for display.
- **Loop protection.** An action that changes the mode again (for example it calls
  `home_modes.set_mode`) is recognised by its context, applied right after the running change
  (not inside it, which would deadlock) and logged as a warning. At most 3 such changes are
  accepted per 60 s; further ones are blocked, logged and recorded as an `action_loop_blocked`
  system entry in the history. Limit: only changes made directly by the action are recognised.
  A change that comes back through another automation is a normal change and waits for the
  running change to finish.

Example (enter actions of the Night mode):

```yaml
- action: light.turn_off
  target:
    area_id: living_room
- action: climate.set_temperature
  target:
    entity_id: climate.bedroom
  data:
    temperature: 18
```

## Services

| Service         | Fields                          | Notes                                                              |
| --------------- | ------------------------------- | ------------------------------------------------------------------ |
| `set_mode`      | `mode`, `override` (optional)   | `override` defaults to true with a user, false without one         |
| `set_overlay`   | `overlay`, `active`             |                                                                    |
| `set_temporary` | `mode`, `duration`              | Reverts to the previous mode when the time is up                   |
| `revert`        |                                 | Back to the previous primary mode                                  |
| `set_auto`      |                                 | Clears the override, re-evaluates auto-rules now                   |
| `clear_history` |                                 | Deletes the history log. **Administrators only**                   |
| `import_input_select` | `entity_id`, `mapping`, `confirm`, `mirror`, `mirror_overlays` | Maps an old input_select to roles; dry run unless `confirm`. **Administrators only**, returns response data. See [migration.md](migration.md) |

`mode` accepts a role id or a role name. `set_temporary`, `revert` and `set_auto` follow the
same permission rules as `set_mode`; `set_auto` is not available to allow-list users.

## Events

`home_modes_changed` is fired for every applied change. Payload for both kinds:

| Field      | Primary change                         | Overlay change                                   |
| ---------- | -------------------------------------- | ------------------------------------------------ |
| `kind`     | `"primary"`                            | `"overlay"`                                      |
| `from`     | previous primary role id               | role id if it was on, else `null`                |
| `to`       | new primary role id                    | role id if now on, else `null`                   |
| `role`     | the new primary role id                | the overlay role id                              |
| `active`   | `true`                                 | `true` when switched on, `false` when switched off |
| `overlays` | active overlay role ids after the change | same                                           |
| `source`   | `manual`, `schedule`, `sensor`, `presence`, `alarmo`, `temporary_expiry`, `system` | same |
| `rule`     | rule name or `null`                    | rule name or `null`                              |
| `user_id`  | user id or `null`                      | user id or `null`                                |

The `source` of a change made through the Alarmo bridge is `alarmo`. Both events are described
in the logbook ([history.md](history.md)).

`home_modes_denied` is fired when a user is denied: `role` (null for the auto switch / set_auto),
`user_id`, `source`, `reason` (`not_in_allow_list`, `allow_list_user`, `unknown_user`).

## Device triggers and conditions

Not provided. Home Assistant's documentation says device automations do not accept new
implementations. Use a state trigger on `select.home_mode` / the binary sensors, or an event
trigger on `home_modes_changed`.

## Dashboard cards, Assist, migration, diagnostics (Step 5)

- **Cards** (`custom:home-modes-card`, `custom:home-modes-guest-card`): [cards.md](cards.md).
  They are served and loaded automatically; the visual editor needs no resource.
- **Guest dashboard:** [guest-dashboard.md](guest-dashboard.md). The websocket command
  `home_modes/allowed_roles` (any signed-in user) returns only the roles the caller may set
  (`modes`, `overlays` with `id`, `name`, `type`, `icon`) and `can_set_auto`. It never returns
  other users' rules.
- **Assist:** intents `HomeModesSetMode` and `HomeModesSetOverlay`, with sentences you copy:
  [assist.md](assist.md).
- **Migration from an input_select**, including the optional mirror (off by default, a
  temporary aid): [migration.md](migration.md). Options key `mirror`:
  `{enabled, entity_id, mapping: {role id: option}, overlays}`. `overlays` (default false) is
  the "Mirror overlays" option.
- **Companion apps:** [companion-apps.md](companion-apps.md).

### Diagnostics

Settings → Devices & services → Home Modes Advanced → Download diagnostics. Included: versions
(integration, Home Assistant, Python), the state (primary, previous, since, overlays, auto flag,
override, temporary), armed timers, the roles (ids, types, enabled, number of actions), a
summary of every setting and the last 50 history entries.

Redacted or reduced to counts: user ids and names, notification targets, services, titles and
message templates, the Alarmo entity id, the vacation lights, the person entities, sensor
entity ids, the input_select used by the mirror, and the **names** of custom or renamed roles.
Action contents are not included (only their number). History entries keep role ids, source and
rule; users become a `had_user` flag; bridge notes keep only reason, event, role, state and
result.
