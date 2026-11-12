# Debug logging

Add to `configuration.yaml` (or use Settings → Devices & services → Home Modes Advanced → Enable
debug logging):

```yaml
logger:
  default: warning
  logs:
    custom_components.home_modes: debug        # everything below
    # or only parts:
    custom_components.home_modes.engine: debug
    custom_components.home_modes.alarmo: debug
```

## Loggers

| Logger | What it logs |
| --- | --- |
| `custom_components.home_modes.engine` | changes ignored because of an override (`debug`); denied changes with the **user id** and reason (`warning`); changes requested by actions and blocked loops (`warning`); failing pipeline hooks (`exception`) |
| `custom_components.home_modes.actions` | failing or timed-out enter/exit actions: phase, index, role id and the error text limited to 200 characters (`warning`); the script runner's own run messages |
| `custom_components.home_modes.alarmo` | bridge errors with their code and detail (`warning`), states ignored as our own echo (`debug`), waiting for an Alarmo entity (`info`) |
| `custom_components.home_modes.notify` | failing notifications with a **shortened** target and the error **type** only (`warning`), failing templates with the error type only (`warning`), suppressed messages with the reason only (`debug`) |
| `custom_components.home_modes.vacation` | replay fallback to random (`warning`), failing lights with the entity id and the error type (`warning`), recorder query failures (`debug`) |
| `custom_components.home_modes.coordinator` | invalid role definitions (role id only) and corrupt stored state (`warning`) |
| `custom_components.home_modes.mirror` | failed writes to the old input_select: reason and role id (`warning`), the error type of a failed service call (`debug`) |
| `custom_components.home_modes.frontend` | whether the card module was registered or why not (`debug`) |
| `custom_components.home_modes.assist` | nothing of its own; answers go to the user. Intent handling is logged by `homeassistant.components.conversation` |
| `custom_components.home_modes.presence` | failing presence listeners (`exception`) |
| `custom_components.home_modes.autorules` | rule evaluation problems |

The websocket commands (`home_modes/history`, `home_modes/allowed_roles`) and the migration
helper log nothing themselves; Home Assistant's own `homeassistant.components.websocket_api`
logger shows command errors.

## What is never logged

- **Alarm codes.** The integration never reads, stores or sends a code (see
  [alarmo-and-ring-blueprint.md](alarmo-and-ring-blueprint.md)).
- **Message and title templates and rendered messages.** Only the type of a template error is logged.
- **Full notification targets.** Targets are shortened to 8 characters in logs
  (`mobile_a…`). The history (administrators only) and the options do contain the full target;
  diagnostics redact it.
- **Action contents.** Only the error text returned by Home Assistant or the called integration
  is logged; that text can contain entity ids.

What does appear: role ids and names, entity ids of lights (vacation simulation) and of Alarmo
(bridge errors), and user **ids** (not names) of denied attempts. These are not secrets, but
review a log before posting it publicly.

The diagnostics download (Devices & services → Home Modes Advanced → Download diagnostics) is
redacted; see [history.md](history.md) for what the history contains.
