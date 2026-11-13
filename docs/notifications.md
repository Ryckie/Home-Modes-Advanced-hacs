# Notifications

Nothing is sent until you add a rule with at least one target (Configure →
Notifications → Add a rule). A rule without a target never sends.

## Events

| Event | Fires when | Android channel | Importance | iOS interruption level |
| --- | --- | --- | --- | --- |
| `changed_to` (+ a mode) | that mode or overlay becomes active | `HM_ModeChanges` | `low` | `passive` |
| `any_change` | every applied change | `HM_ModeChanges` | `low` | `passive` |
| `vacation_entered` | primary mode becomes `vacation` | `HM_ModeChanges` | `low` | `passive` |
| `guest_on` | the guest overlay is switched on | `HM_Guests` | `default` | `active` |
| `denied` | a user is refused (permissions) | `HM_Alerts` | `high` | `time-sensitive` |
| `bridge_error` | an Alarmo bridge error | `HM_Alerts` | `high` | `time-sensitive` |

## Precedence

If several rules would send the **same text to the same target** for one change, only the most
specific rule is sent, in this order: `guest_on`, `vacation_entered`, `changed_to`,
`any_change`. The others are suppressed. Rules with different text are all sent.

**Nothing is suppressed silently.** Every suppressed message writes a history entry of kind
`system` with rule `notification_suppressed` and the note `{reason, target, event}`:

| `reason` | Meaning |
| --- | --- |
| `most_specific_rule_wins` | a more specific rule already sent this text to this target for this change |
| `rate_limited` | the same text was sent to this target within the rate limit (default 10 s) |

These entries are visible to administrators only (see [history.md](history.md)). A rate limit of
0 sends every duplicate, including the ones the precedence would suppress.

## Test a rule

Configure → Notifications → **Send a test notification**, pick a rule and press
Submit. Every target of that rule gets a test message with the rule's channel and priority;
the duplicate rate limit does not apply. The screen shows per target whether it was sent or
why it failed (for example an unknown service or a phone that is not connected).

## Targets

The rule screen has two target fields because Home Assistant has two kinds of notify targets:

- **Notify entities** are the current style (`notify.*` entities). Phones from the Companion
  app and integrations that have moved over show up here. Prefer this field.
- **Notify services** are the older style (`notify.<name>` actions). Many integrations still
  only offer this, and notify groups exist only here. Use it for targets that are missing from
  the entity list.

A phone shows up in both lists. Pick it once: both routes send the same `HM_` channel data.

- **Companion app notify entities** (`notify.<phone>`, from the Mobile App integration): sent
  through that phone's `notify.mobile_app_<device>` service (or `notify.mobile_app` with the
  phone as target) **with** the Companion app fields below. `notify.send_message` cannot carry
  them, so the phone would otherwise put the notification in its default "General" channel.
- **Other notify entities** (`notify.*`): sent with `notify.send_message` (message and title only).
- **Notify services** such as `mobile_app_<device>`: sent with `notify.<service>`; the data
  contains the Companion app fields:

```yaml
message: "Home mode: Home → Night"
title: "Home Modes"
data:
  channel: HM_ModeChanges      # Android
  importance: low              # Android
  group: HM_ModeChanges        # iOS thread / Android group (one stack per channel)
  push:
    interruption-level: passive   # iOS: passive | active | time-sensitive
```

Android and iOS fields are sent together; each app ignores the other's. Android applies a
channel's importance only the first time the channel is created on the device; change it
afterwards in the Android notification settings. Field names checked against the Companion app
documentation (basic notifications): `data.channel`, `data.importance`
(`min|low|default|high|max`), `data.group`, `data.push.interruption-level`. iOS has no channels:
the `HM_` name groups the notifications (`group`) and `interruption-level` sets how they interrupt.

## Templates

Message and title are Jinja templates. Variables (the same names are used in action templates,
see [configuration.md](configuration.md)):

| Variable | Value |
| --- | --- |
| `from_role`, `to_role` | role ids (stable: they do not change when a mode is renamed) |
| `from_mode`, `to_mode` | aliases of `from_role` / `to_role`, **always role ids** |
| `from_name`, `to_name` | display names, for text only |
| `role`, `role_name` | id and name of the mode or overlay that changed |
| `source` | `manual`, `schedule`, `sensor`, `presence`, `alarmo`, `temporary_expiry`, `system` |
| `rule` | rule name or denial reason |
| `user` | name of the user, empty for automations |
| `time` | local time `HH:MM` |

Empty values are empty strings (for an overlay that is switched on, `from_role` is empty).
Use ids for logic and names for display: `{% if to_role == 'night' %}…{% endif %}`.

`from` is a reserved word in Jinja and is **not available**: `{{ from }}` renders empty. Use
`from_role` or `from_name`. A message that renders empty falls back to the default text; a
template that fails to render falls back too and logs a warning. Templates are validated in the
options flow.

```
{{ user or 'Someone' }} set {{ to_name }} at {{ time }}
```

## Rate limit and failures

The same message is not sent to the same target more than once within 10 seconds
(configurable, 0 disables). A failing notification (offline device, unknown service) is logged
and never blocks or delays the mode change; the other targets are still tried.

Mode changes made by the vacation simulation never notify (see
[vacation-simulation.md](vacation-simulation.md)).
