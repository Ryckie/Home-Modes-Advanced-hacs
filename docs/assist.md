# Assist (voice and text)

The integration registers two **intents** that Assist can trigger:

| Intent | Slots | Does |
| --- | --- | --- |
| `HomeModesSetMode` | `mode` (a mode name or id) | Sets the house mode |
| `HomeModesSetOverlay` | `overlay` (name or id), `state` (`on` or `off`) | Turns an overlay such as Guest or Do not disturb on or off |

## Sentences: you add them (an integration cannot ship them)

Home Assistant's default conversation agent loads sentences only from its built-in intents
package and from `<config>/custom_sentences/<language>/*.yaml`. There is no mechanism for a
custom integration to supply sentence files (checked in the Home Assistant source for both
2026.10.4 and 2026.11.1: `homeassistant/components/conversation/default_agent.py`). So this
integration ships the **handlers**, and you copy a ready-made English sentence file:

1. Copy [examples/home_modes_sentences.yaml](examples/home_modes_sentences.yaml) to
   `<config>/custom_sentences/en/home_modes.yaml`.
2. Restart Home Assistant (or reload the conversation sentences).
3. Try: "set the house mode to night", "turn on the guest mode", "turn do not disturb mode
   off".

```yaml
language: "en"
intents:
  HomeModesSetMode:
    data:
      - sentences:
          - "set [the] house mode to {mode}"
          - "switch [the] house to {mode} mode"
          - "change [the] house mode to {mode}"
  HomeModesSetOverlay:
    data:
      - sentences:
          - "turn {state} [the] {overlay} mode"
          - "turn [the] {overlay} mode {state}"
lists:
  mode:
    wildcard: true          # whatever you say is looked up by name or id
  state:
    values:
      - { in: "on", out: "on" }
      - { in: "off", out: "off" }
  overlay:                  # "out" must be the overlay's role id
    values:
      - { in: "guest", out: "guest" }
      - { in: "do not disturb", out: "dnd" }
```

This exact file is used by the test suite (`tests/test_intent.py`), which says the sentences
through the conversation agent and checks the result. Add more sentences or languages by
copying the pattern.

## Answers

- "House mode set to Night." / "The house is already in Night mode."
- "Guest is now on." / "Guest is already off."
- Unknown name: "I don't know a mode called Banana."
- A mode that is turned off in the options: "Vacation is turned off in Home Modes."
- Asking for an overlay as a mode (or the reverse): "Guest is an overlay, not what you asked
  for."
- Not allowed: "You are not allowed to change Night."

## Permissions

The intent runs the same server-side check as the services, as the **user of the conversation**
(`context.user_id`). Typing into Assist in the app or the browser carries your user, so a guest
on an allow-list is refused and the attempt is recorded in the history.

**Limit:** voice satellites and other devices usually send **no user**. A change without a
user is trusted, exactly like an automation. So permissions cannot restrict who speaks to a
satellite. Do not rely on the allow-list to limit voice commands from a shared device.
_(Verified in the source that the intent carries the conversation's context; which clients
fill in the user was not tested on real devices.)_

## Not provided

Per-mode sentences generated from your role names (they would need to be regenerated at every
rename), and exposing the select entity to Assist. See
[companion-apps.md](companion-apps.md) for the question of per-role button entities.
