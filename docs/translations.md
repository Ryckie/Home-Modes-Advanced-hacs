# Translations

Home Modes is English only in v1 but translation-ready. This page lists what is already
translatable, every user-visible string that is **not** yet translatable, and the exact steps
to add a language.

## What is translatable today

Everything in `custom_components/home_modes/translations/en.json` (the only translation
source; there is no `strings.json`, because custom integrations load only `translations/`):

| Top-level key | Contents |
| --- | --- |
| `config` | Setup flow (preset picker) |
| `options` | Every options-flow menu, form, field label, description and error |
| `selector` | Labels of selector options (override modes, strategies, directions, ...) |
| `entity` | Names of the role binary sensors, sensors and switches |
| `exceptions` | Error messages shown when a service call fails |
| `services` | Names and descriptions of the services and their fields |

## Strings that cannot be translated yet

These are written in English in the code or stored in English on purpose. They are listed so
that a translator knows what will still show in English.

### Import flow (options flow, "Import from input_select")

Hard-coded in `config_flow.py` and `migration.py` (accepted for v1):

| String | Where |
| --- | --- |
| `New custom mode (keep this name)` | option label in the mapping step (`config_flow.py`) |
| `Skip this option` | option label in the mapping step (`config_flow.py`) |
| `<name> (<id>)` role labels | mapping step (format string, `config_flow.py`) |
| `skipped`, `new custom mode`, `(<action>, was <name>)` | preview lines (`describe_plan`, `migration.py`) |
| `nothing found` and the group names `automations`, `scripts`, `templates` | usage report in the confirm step (`config_flow.py`, `migration.py`) |
| `Mirror to old input_select`, `Mirror overlays` values `on` / `off` | confirm step placeholders (`config_flow.py`) |
| Problem codes such as `unknown_option:<x>`, `duplicate_role:<x>` | error placeholder (`migration.py`) |
| `home_modes.import_input_select` response keys and snippets | service response data (not meant to be translated) |

### Other places

| String | Where | Why it is English |
| --- | --- | --- |
| Default role names `Home`, `Night`, `Away`, `Vacation`, `Guest`, `Do not disturb`, `All home`, `All away`, `Custom` | `const.py` (`DEFAULT_ROLE_NAMES`) | They are stored in the config entry at setup and become the user's own, editable names (the select options). Rename them in the options flow. |
| Notification default texts (`Home mode: A → B`, `<role> turned on/off`, `Denied: ...`, `Alarmo bridge: ...`) and the default title `Home Modes` | `notify.py` | Used only when the rule has no template. Write a message template in the rule to localise. |
| Notification channel names `HM_ModeChanges`, `HM_Alerts`, `HM_Guests` | `notify.py` | Channel ids are identifiers; Android shows the id as the channel name. |
| Logbook sentences (`changed from A to B`, `turned on`, `denied change of ...`, `source:`, `rule:`) | `logbook.py` | The logbook platform has no translation lookup for custom text. |
| Assist replies (`House mode set to <name>.`, `<name> is already ...`) | `assist.py` | The handler always sets its own speech text. Verified in HA source (`conversation/default_agent.py`): a handler that leaves the speech empty gets a reply from `responses.intents.<Intent>` in a custom sentence file, so a v1.x change could make replies translatable. Not done in v1 (no new features). |
| History entries (rule names such as `presence_all_away`, `mirror_failed`, reasons) | `history.py`, `autorules.py`, `mirror.py` | Machine readable on purpose (automations and cards compare them). |
| Card texts (`Auto on`, `Manual change until`, `Not allowed`, ...) | `frontend/home-modes-cards.js`, constants `TEXT` and `LABELS` and the layout options | The cards do not read `hass.language` yet. |
| Custom card editor option labels `Compact`, `Full` | `frontend/home-modes-cards.js` | Same as above. |

## Add a language

Example: German (`de`).

1. **Copy the file.** Copy `custom_components/home_modes/translations/en.json` to
   `custom_components/home_modes/translations/de.json`. The file name is the language code
   (a Home Assistant language tag, for example `de`, `fr`, `pt-BR`).
2. **Translate values only.** Keep every key exactly as it is. Translate the text values.
   Keep placeholders such as `{entity_id}`, `{preview}`, `{problems}` unchanged. Keep Markdown
   (`**bold**`, backticks, `\n`) and keep `home_modes.import_input_select` and other
   identifiers in backticks untranslated.
3. **Do not translate** role ids, event names, service names, attribute names or the YAML
   examples. Only text a person reads.
4. **Check the structure.** Compare the keys with English:

   ```bash
   python - <<'PY'
   import json
   def keys(x, p=""):
       if isinstance(x, dict):
           for k, v in x.items():
               yield from keys(v, f"{p}.{k}" if p else k)
       else:
           yield p
   en = set(keys(json.load(open("custom_components/home_modes/translations/en.json"))))
   de = set(keys(json.load(open("custom_components/home_modes/translations/de.json"))))
   print("missing:", sorted(en - de))
   print("extra:", sorted(de - en))
   PY
   ```

   Both lists must be empty.
5. **Validate.** `hassfest` (the `Validate` workflow, or `python -m script.hassfest` in a Home
   Assistant core checkout) checks the translation files.
6. **Test in Home Assistant.** Set your user profile language to German, restart, open the
   options flow, and check the menus, the selector options (override modes) and the service
   descriptions in *Developer tools > Actions*. Strings from the list above stay English.
7. **Optional card translation.** The cards use a `TEXT` and a `LABELS` constant. Adding a
   language there is a code change (read `hass.language`, pick a table) and is not part of
   v1.
8. Open a pull request (see CONTRIBUTING.md). A translation PR must not change keys in
   `en.json`.

Moving the hard-coded import-flow labels into `en.json` (using `selector` translation keys and
description placeholders) is a possible v1.x change.
