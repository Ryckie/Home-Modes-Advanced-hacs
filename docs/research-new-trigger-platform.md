# Research note: the new `trigger.py` / `condition.py` platforms

Status: research only. Nothing in this note is built. Checked against Home Assistant
2026.10.4 and 2026.11.1 (source read from the installed packages, plus a throw-away spike
that is not part of the repository).

## Question

Home Assistant now has trigger and condition platforms that an integration registers in
`trigger.py` / `condition.py` (with `triggers.yaml` / `conditions.yaml`), as the successor of
device triggers and device conditions. Can a **custom** integration use them, and should
Home Modes Advanced?

## Findings

1. **Technically yes.** The loader does not restrict the platforms to built-in integrations:
   - `homeassistant/helpers/trigger/__init__.py` (`_async_get_trigger_platform`) resolves the
     integration with `async_get_integration(hass, platform)` and loads
     `integration.async_get_platform("trigger")`. There is no built-in-only check.
   - `helpers/trigger/descriptions.py` loads `integration.file_path / "triggers.yaml"` for
     the UI descriptions. `helpers/condition/__init__.py` and `helpers/condition/descriptions.py`
     do the same for `condition` and `conditions.yaml`.
2. **Spike result (both versions).** A minimal custom integration with `trigger.py`
   (`async_get_triggers()` returning `{"role_on": RoleOn}`, a `Trigger` subclass with
   `async_validate_config` and `async_attach_runner`) and a `triggers.yaml` was loaded by the
   test harness on 2026.10.4 and 2026.11.1. An automation using
   `trigger: spike_trig.role_on` with `options: {role: night}` was set up, fired when the
   event arrived, and the trigger appeared in `async_get_all_descriptions()`.
3. **The API is young.** Two details found while writing the spike:
   - `async_attach_runner(run_action, did_not_trigger=None)` has a second parameter that
     older documentation examples do not show. My first attempt with only `run_action`
     failed with a `TypeError`. A signature change of this kind is exactly the churn risk.
   - Validation goes through `async_validate_complete_config`, which splits `options` and
     `target` out of the config before calling `async_validate_config`.
4. **Documentation status.**
   - developers.home-assistant.io/docs/automations: "The features in this page are still in
     very active development and should not be used yet by integrations."
   - contributors.home-assistant.io/core/integrations/triggers-and-conditions/: the API is
     "in use, but it is young and still changes often"; device triggers are "an older
     mechanism that does not accept new implementations"; hassfest requires `triggers.yaml`
     for registered triggers.
   - github.com/home-assistant/architecture discussion #1510: option fields of the new-style
     triggers are static; they cannot be built from runtime state. This matters here because
     role names are user-editable.

## What it would give Home Modes

- A trigger such as "Home Mode: role became active", with a role selector in the automation
  editor.
- The role ids are static (`home`, `night`, `away`, `vacation`, `guest`, `dnd`, `all_home`,
  `all_away`, `custom_1` to `custom_10`), so a static `select` would work. The labels in
  that select could not show the **renamed** names the user chose, only the ids or fixed
  English labels.

## What it would cost

- A second public API to keep stable (option names, payload variables).
- Exposure to API changes that the documentation says are still coming.
- Another test matrix across HA versions; the custom-integration path is not documented as
  supported.

## What users already have

- `binary_sensor.home_mode_<role>`: a state trigger or condition that survives renames.
- The `mode_id` / `role` attributes on `select.home_mode`.
- The `home_modes_changed` event with the full payload.
- Three blueprints that use these (see `docs/examples.md`).

## Recommendation

**Do not build it for 1.0.** The benefit over a state trigger on the role sensor is small,
renamed labels cannot be shown, and the API is documented as unstable for integrations.

Revisit when all of these hold:

- the developer documentation no longer says integrations should not use it;
- a plain `async_attach_runner` signature is stable for at least two releases;
- users ask for it in issues.

The spike used for this note is not shipped. Re-creating it takes about 40 lines
(a `Trigger` subclass, `async_get_triggers`, a `triggers.yaml`).

## Sources

- https://developers.home-assistant.io/docs/automations
- https://contributors.home-assistant.io/core/integrations/triggers-and-conditions/
- https://github.com/home-assistant/architecture/discussions/1510
- Home Assistant source (2026.11.1): `helpers/trigger/__init__.py`,
  `helpers/trigger/models.py`, `helpers/trigger/descriptions.py`,
  `helpers/condition/__init__.py`, `helpers/condition/descriptions.py`, `loader.py`
  (`Integration.async_get_platform`).
