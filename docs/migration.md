# Migrating from an input_select

If your house mode lives in an `input_select` (Home / Night / Away / ...), the import helper maps
its options to Home Modes roles, shows a preview, and lists everything that still uses the old
helper. **It never edits or deletes your automations, scripts, helpers or YAML.** Nothing is
written until you confirm.

## Two ways to run it

- **Options flow:** Settings → Devices & services → Home Modes Advanced → Configure →
  *Integrations* → **Import from input_select**. Pick the input_select, check the suggested
  target of every option, see the preview and the usage report, then confirm.
- **Action:** `home_modes.import_input_select` (administrators only). Without `confirm: true` it
  is a dry run that returns the suggestions, the preview, replacement snippets and the usage
  report as response data. Developer tools → Actions shows the response.

```yaml
action: home_modes.import_input_select
data:
  entity_id: input_select.house_mode
  # mapping:            # optional, per option; anything you leave out uses the suggestion
  #   Movie: custom     # new custom mode
  #   Party: skip       # not imported
  #   Living: home      # an existing role id
  # confirm: true       # write the result (renames/enables roles, adds custom modes)
  # mirror: true        # only together with confirm, see "Mirror" below
```

## How options are matched

Checked in this order; the first match wins, and a role is suggested at most once (a second
match becomes a custom mode):

1. An existing role with exactly the same name (case-insensitive) — so running the helper twice
   is harmless.
2. By words in the name: `do not disturb` / `dnd` / `quiet` → **Do not disturb**; `guest` /
   `visitor` → **Guest**; `vacation` / `holiday` → **Vacation**; `away` / `out` / `leaving` →
   **Away**; `night` / `sleep` / `bed` → **Night**; `home` / `house` / `present` → **Home**.
3. Anything else → a **custom mode** (up to 10; further options are skipped).

Every option can be changed to any existing mode or overlay, *new custom mode* or *skip*. Two
options cannot point to the same role.

**Names stay as you had them.** A mapped role is renamed to the exact text of the option and
enabled; a custom mode gets that text as its name. Roles that no option maps to are left as
they are. The preview shows the action per option: `keep`, `rename`, `enable`, `rename+enable`,
`create`, `skip`. Invalid mappings (two options to one role, a name that clashes with another
mode, no enabled primary left) are refused with the reason, and nothing is written.

## The usage report (read-only)

Next to the preview you get the automations, scripts and template helpers that mention the old
input_select:

- **Automations and scripts:** found through Home Assistant's own loaded configuration (entity
  references) and a text search of each automation's and script's configuration, which also
  finds templates such as `is_state('input_select.house_mode', 'Night')`. Each entry lists
  which options it mentions.
- **Template helpers created in the UI:** found through their stored options.

**Not found:** template sensors written in YAML, dashboards, blueprints' internals that only
build the entity id at run time, and anything outside Home Assistant (Node-RED, AppDaemon).
Search your files for the entity id as well.

The action response also contains `snippets`: a replacement per mapped option that you copy
into your own automations, for example for the option "Night" mapped to `night`:

```yaml
# condition, was: state of input_select.house_mode is "Night"
condition: state
entity_id: binary_sensor.home_mode_night
state: "on"

# trigger, was: input_select.house_mode changed to "Night"
trigger: state
entity_id: binary_sensor.home_mode_night
to: "on"
```

`entity_exists_yet` in the response is false for a custom mode that does not exist until the
import is confirmed; its entity id is predicted from the role id.

## Mirror to the old input_select (temporary migration aid)

Off by default. When on, Home Modes writes the matching option to your old input_select after
**every** mode change, so automations that still react to the input_select keep working while
you move them over.

- **One direction only.** Home Modes never reads the input_select. Changing the input_select by
  hand does not change the house mode.
- **Which option.** The option mapped to the active primary mode. Overlays are **not** mirrored
  unless you turn on the separate option **Mirror overlays** (service field `mirror_overlays`,
  options key `mirror.overlays`, off by default). When it is on, the most recently activated
  overlay that has a matching option is written while it is active (if two overlays are on,
  the one turned on last wins). An overlay without a matching option falls back to the primary
  mode's option and is not a failure. When the overlay ends, the current primary mode's option
  is written again.
- **Loop guard.** A write is skipped if the input_select already shows the option. A change
  requested by an automation that reacted to the mirror's write is handled like a change
  requested by an enter/exit action: applied after the running change, at most 3 within 60 s,
  then blocked and recorded as `action_loop_blocked` in the [history](history.md).
- **Failures are recorded**, never silent. A history entry `mirror_failed` (kind `system`) has
  the reason: `option_not_in_input_select` (you renamed or removed that option; matching is
  exact, including letter case), `no_option_mapped` (the active mode was skipped or has no
  option), `input_select_missing` (the entity is gone), `service_call_failed`.
- Turn it off when you have moved your automations: run the helper again and untick the mirror
  box (or set `mirror: false` with `confirm: true`).

## Worked example 1: Home / Night / Away / Vacation

Old helper `input_select.house_mode` with options `Home`, `Night`, `Away`, `Vacation`.

1. Run the helper. Suggestions: Home → `home`, Night → `night`, Away → `away`,
   Vacation → `vacation`. Preview: all `keep` (the names already match).
2. Confirm, with the mirror on. Result: the same four modes, `select.home_mode` and
   `binary_sensor.home_mode_<role>` entities, plus the mirror.
3. Move automations one by one using the snippets, then turn the mirror off.

## Worked example 2: a household with extra modes

Old helper options: `At home`, `Sleeping`, `Out`, `Holiday`, `Guests`, `Movie night`, `Party`.

| Option | Suggested | Why |
| --- | --- | --- |
| At home | `home` (rename to "At home") | contains `home` |
| Sleeping | `night` (rename to "Sleeping") | contains `sleep` |
| Out | `away` (rename to "Out") | the word `out` |
| Holiday | `vacation` (rename to "Holiday") | contains `holiday` |
| Guests | `guest` (overlay, rename to "Guests") | contains `guest` |
| Movie night | custom mode | `night` is already taken by "Sleeping", so it does not match twice |
| Party | custom mode | no match |

Notes: **Guests** becomes the *Guest overlay*, not a primary mode, because Home Modes models
guests as something that is on in addition to Home. If you would rather keep "Guests" as a
primary mode, change that option to *new custom mode* in the mapping step. With the mirror on,
the old input_select shows "Guests" while the overlay is on and the primary option again when
it is off.

## Replacing input_select logic: copy-paste examples

```yaml
# Condition: Night is active (rename-proof)
condition:
  - condition: state
    entity_id: binary_sensor.home_mode_night
    state: "on"

# Trigger: the primary mode changed (select attribute holds the role id)
trigger:
  - trigger: state
    entity_id: select.home_mode
    attribute: mode_id
    to: night

# Trigger: event, with source and user
trigger:
  - trigger: event
    event_type: home_modes_changed
    event_data:
      kind: primary
      to: away

# Condition on the role attribute (role type; custom modes are "custom", ids are custom_1 ...)
condition:
  - condition: state
    entity_id: select.home_mode
    attribute: role
    state: night
```

More in [examples.md](examples.md).
