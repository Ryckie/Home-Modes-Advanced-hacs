# Smoke test (about 10 minutes)

For a **fresh Home Assistant OS test instance** (not your production house). Nothing here has
been run on a real instance yet; it is the script for the first real run. Note the result of
every step. If a step fails, stop and attach what the step says (see "If something fails").

Needs: Home Assistant 2026.10.4 or newer, HACS installed (for 2026.10.x), one `person`
entity, one light (a demo or template light is fine), a phone or browser logged in as admin.

## Steps

| # | Do | Expected |
|---|---|---|
| 1 | HACS → three-dot menu → Custom repositories → add `https://github.com/Ryckie/Home-Modes-Advanced-hacs`, category **Integration**. Enable "Show beta versions" if v0.9.1 is not listed. Open the repository → Download → choose v0.9.1. (On 2026.11 use Settings → Marketplace instead; UNVERIFIED.) | The repository is added, version **0.9.1** is offered and downloads without errors |
| 2 | Settings → System → Restart Home Assistant. | Starts normally; the log shows no `home_modes` errors |
| 3 | Settings → Devices & services → Add integration → **Home Modes Advanced** → preset **Simple** → Submit. | One device "Home Mode" with `select.home_mode` = Home, `binary_sensor.home_mode_home` on, `sensor.home_mode_since`, `switch.home_mode_auto` on. No Guest or DND entities |
| 4 | Remove the integration (⋮ → Delete), then add it again with preset **Extended**. | Extra entities: `binary_sensor.home_mode_guest`, `..._dnd`, `..._all_home`, `..._all_away`, `switch.home_mode_overlay_guest`, `..._dnd`. Removal in step 4 left no orphaned entities |
| 5 | Developer tools → Actions → `home_modes.set_mode` with `mode: night` (or use the select). | `select.home_mode` = Night, `binary_sensor.home_mode_night` on, `..._home` off, `sensor.home_mode_trigger_reason` shows a manual change. A `home_modes_changed` event is fired (Developer tools → Events → listen) |
| 6 | Turn on `switch.home_mode_overlay_guest`. | The Guest binary sensor is on; the primary mode stays Night |
| 7 | Settings → Automations & scenes → Blueprints → Import blueprint (or the button in [blueprints.md](blueprints.md)) → **Lights off at night** → create an automation with your light and the default night sensor. Turn the light on, then set mode `home`, then `night`. | The light turns off when the mode becomes Night (not when it is already Night and not at a reload) |
| 8 | Options (Configure) → rename "Night" to "Sleep". Set the mode to Home, then Night again. | The select now shows "Sleep"; the blueprint automation still works |
| 9 | Dashboard → Edit → Add card → search "Home Modes" (or YAML `type: custom:home-modes-card`). | The card loads (hard-refresh the browser once if it does not), shows the current mode, mode buttons and Auto; tapping a button changes the mode |
| 10 | Settings → System → Restart Home Assistant. Then look at the select, the Since sensor and Auto. | The mode, overlays and the Auto switch are the same as before the restart; the Since time is unchanged |
| 11 | Settings → Devices & services → Home Modes Advanced → ⋮ → Download diagnostics. Open the file. | It downloads; it contains no person names, notification targets or Alarmo ids |

## Expected log

Settings → System → Logs, filter `home_modes`: only the usual Home Assistant warning that this
is a custom integration. No tracebacks.

## If something fails

Attach to a GitHub issue (use the bug report template):

- the **diagnostics download** (step 11; works from any step after step 3);
- a **debug log**: add the `logger:` block from [debug-logging.md](debug-logging.md), redo the
  failing step, then attach Settings → System → Logs → Download full log, or the lines containing `home_modes`;
- which step number failed, the Home Assistant version and the HACS or Marketplace version shown.

Specific hints:

- Step 1, version 0.9.1 not shown: say which listing you used (HACS or Marketplace) and whether
  beta versions were enabled. This is an open question (UNVERIFIED).
- Step 3, integration not found: restart again and clear the browser cache; attach the log lines
  about `custom_components/home_modes` or "Integration not found".
- Step 9, card not found: hard-refresh; check Settings → Dashboards → Resources (the module is
  registered automatically, no resource should be needed). See [cards.md](cards.md).
- Step 7, light does not turn off: open the automation's trace (⋯ → Traces) and attach it.
