# Repository layout

This list is checked by `tests/test_release_files.py`: every module, workflow, blueprint and
top-level file must appear here, and nothing listed may be missing.

```
custom_components/home_modes/
  __init__.py         setup, services, wiring of the hooks, storage version guard
  actions.py          enter/exit actions (EXIT_ACTIONS / ENTER_ACTIONS hooks)
  alarmo.py           optional Alarmo bridge (ALARMO hook + state listener, loop guard)
  assist.py           Assist intents (HomeModesSetMode, HomeModesSetOverlay)
  autorules.py        orchestrator of presence/night/morning rules, timers, startup catch-up
  binary_sensor.py    one binary sensor per enabled role
  config_flow.py      config flow and options flow (including the integrations sub-menu)
  const.py            constants, storage versions
  coordinator.py      roles, settings, state store
  diagnostics.py      redacted diagnostics download
  engine.py           the change pipeline and its hook points
  frontend.py         serves frontend/ and loads the module on every dashboard
  history.py          persistent history log (HISTORY hook)
  logbook.py          logbook descriptions of the events
  migration.py        input_select import helper: suggestions, plan, usage report
  mirror.py           optional one-way mirror to the old input_select (NOTIFY-stage hook)
  models.py           Role, state, change and request dataclasses
  night.py            night/morning window helpers (DST-safe)
  notify.py           notification rules (NOTIFY hook)
  permissions.py      server-side user rules
  presence.py         person tracking
  select.py           select.home_mode
  sensor.py           since / previous / trigger reason sensors
  settings.py         parsed options (automation, Alarmo, vacation, notifications, history)
  switch.py           auto switch and overlay switches
  template_vars.py    variables available in notification templates
  vacation.py         vacation simulation
  ws.py               websocket commands home_modes/history and home_modes/allowed_roles
  manifest.json, services.yaml
  frontend/           home-modes-cards.js (the two cards and their editors; plain JS)
  brand/              icon.png, icon@2x.png, logo.png, logo@2x.png, dark_logo.png, dark_logo@2x.png
  translations/       en.json (the single source of strings)
blueprints/automation/home_modes/
  heating_setback_away_vacation.yaml
  lights_off_at_night.yaml
  notify_vacation_or_guest.yaml
docs/                 documentation; docs/examples/ holds the Assist sentence file
tests/                pytest suite (pytest-homeassistant-custom-component)
tests/js/             browserless card checks (node + jsdom), not shipped
.github/workflows/    validate.yml (hassfest, HACS), tests.yml, release.yml
.github/scripts/      release_info.py (release checks, used by release.yml)
.github/ISSUE_TEMPLATE/  bug_report.yml, feature_request.yml, config.yml
.github/PULL_REQUEST_TEMPLATE.md, .github/dependabot.yml
CHANGELOG.md, CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, LICENSE, README.md
hacs.json, pyproject.toml, pytest.ini, requirements_test.txt
```

Pipeline order for every change (`engine.py`): permission → priority → role checks → **exit
actions** → state change → **enter actions** → `home_modes_changed` event → **history** →
**notify** → **Alarmo**.
