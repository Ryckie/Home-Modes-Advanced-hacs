# Final audit against the brief (version 0.9.0)

Sources: the master brief, the amendments of Steps 2 to 6 and the answers given after each step.
"Test" names the file (and test) that proves the item; "n/a" means it is not testable
automatically. Status: **done**, **partly**, **missing**, **deviated** (changed by a later decision).

Numbers, from a clean environment with the exact commands of `.github/workflows/tests.yml`
(Python 3.14.6, fresh virtual environments):

| Job | Command | Result |
|---|---|---|
| Home Assistant 2026.10.4 | `pytest --cov-fail-under=90` | **325 passed**, 0 skipped, 0 failed; coverage **98.22 %** (3262 statements, 58 missed) |
| Home Assistant 2026.11.1 | `python tests/run_pytest_ha2611.py --cov-fail-under=90` | **325 passed**, 0 skipped, 0 failed, 1 warning; coverage **98.22 %** (3262 statements, 58 missed) |
| Cards | `node --check` and `npm test` (Node 22) | 11 tests, 11 passed, 0 skipped |
| Lint | `ruff format --check`, `ruff check` (0.17.5), `mypy` (2.4.1) | clean, 66 files, 28 source files |

Coverage varies by about 0.03 points between runs (58 or 59 missed statements; timing-dependent branches).
The `pytest -v` variant also passes (325).

The GitHub workflows and everything on real devices have **not** been run.

## 1. Safety rules

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| Alarmo is never disarmed automatically | `alarmo.py` (a mapping to disarmed needs `allow_disarm`, off by default) | `test_alarmo.py::test_never_disarms_by_default`, `test_safety_claims.py::test_disarm_mapping_without_switch_blocks_every_source`, `test_alarmo.py::test_disarm_only_with_explicit_switch`, `test_alarmo.py::test_apply_auto_arms_but_never_disarms_without_switch`, `test_alarmo.py::test_startup_reconcile_never_touches_alarmo` | done | Needs a real Alarmo to confirm (checklist) |
| Auto-rule changes (rank 2 to 4) do not touch Alarmo unless "apply auto-rule changes" is on | `alarmo.py`, `settings.py` | `test_alarmo.py::test_auto_rule_changes_do_not_touch_alarmo`, `test_safety_claims.py::test_real_presence_and_expiry_changes_never_touch_alarmo` | done | |
| No Alarmo code stored or logged | `alarmo.py` (reports `code_required`) | `test_alarmo.py::test_code_required_is_reported_never_stored`, `test_safety_claims.py::test_no_alarmo_code_reaches_a_call_or_a_store`, `test_log_privacy.py` | done | Arming from Home Modes in setups that require a code is not possible by design |
| Permissions enforced server-side only | `permissions.py`, `engine.py`, `ws.py` | `test_services.py::test_service_enforces_permissions`, `test_guest_dashboard.py::test_guest_cannot_bypass_the_card` (services, select and switches), `tests/js/cards.test.mjs` ("the guest card only shows what the server allows and the config can only narrow it"), matrix in [security-and-quality.md](security-and-quality.md) | done | Home Assistant limit: automations are trusted, guests can call other services (documented) |
| Loop guard (Alarmo, actions, mirror) | `alarmo.py` (origin tag, expected-state suppression, 15 s window), `engine.py` (action loop limit) | `test_alarmo.py::test_no_echo_*`, `test_safety_claims.py::test_late_echo_of_our_own_arming_does_not_flip_the_mode_back`, `test_alarmo.py::test_near_simultaneous_changes`, `test_actions.py::test_action_changing_mode_is_deferred_and_loop_limited`, `test_mirror.py::test_one_direction_and_loop_guard` | done | A same-final-state keypad press inside the 15 s window is ignored (documented) |
| Failures never block a mode change (actions, notify, Alarmo, mirror, history) | `engine.py` hook isolation | `test_engine.py::test_hooks_run_in_order_and_failures_are_isolated`, `test_actions.py`, `test_notify.py`, `test_alarmo.py::test_service_error_is_isolated` | done | |
| No cloud, no external dependencies, no network calls | `manifest.json` (`requirements: []`) | `test_release_files.py::test_python_has_no_network_or_dynamic_code`, `test_manifest_has_the_keys_hacs_requires`, `test_frontend.py::test_js_has_no_risky_patterns` | done | See section 8 for the scan |

## 2. Priority ranks and override rules

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| Ranks in one constant: system 0; manual, alarmo, temporary_expiry 1; schedule 2; sensor 3; presence 4 | `models.py::SOURCE_RANKS` | `test_models.py::test_source_ranks` | done | Brief said manual > schedule > presence; amended (Step 2, amendment 8) |
| Higher rank wins; lower ranks ignored while an override is active | `engine.py` | `test_engine.py::test_override_priority`, `test_overrides.py::test_manual_beats_schedule_while_override_active` | done | |
| Schedule beats sensor beats presence in one evaluation | `autorules.py` | `test_overrides.py::test_schedule_beats_presence_in_one_evaluation`, `test_sensor_beats_presence_in_one_evaluation`, `test_schedule_beats_sensor_in_one_evaluation` | done | |
| Override until: end_of_day, next_auto (default), duration, set_auto | `engine.py`, `autorules.py` | `test_overrides.py::test_override_end_of_day`, `test_override_next_auto`, `test_override_duration`, `test_override_set_auto_mode` | done | |
| Override started by a user call; calls without user do not, unless `override: true` | `engine.py`, `__init__.py` | `test_overrides.py::test_override_flag_matrix`, `test_step3_services.py::test_set_mode_override_false_for_user_blocks_nothing` | done | |
| Overrides and timers persist as absolute timestamps; restart re-arms; expired timers applied once in rank order | `coordinator.py`, `autorules.py` | `test_overrides.py::test_restart_*`, `test_lifecycle.py` | done | |
| Temporary modes: revert target, nested keeps first target, re-evaluate auto-rules after expiry | `engine.py` | `test_step3_services.py::test_set_temporary_*`, `test_expiry_*`, `test_nested_temporary_keeps_original_target` | done | |
| DST, time zone and clock jumps | `night.py`, `autorules.py` | `test_time_changes.py` (11 tests) | done | Two bugs found and fixed |
| Vacation entered after continuous all_away for N hours, only if enabled | `autorules.py` | `test_presence.py::test_vacation_after_hours_and_cancellation`, `test_vacation_disabled_stays_away` | done | |
| Unknown/unavailable presence = not changed | `presence.py` | `test_presence.py::test_unknown_and_unavailable_do_not_trigger`, `test_failure_modes.py` | done | |
| Night methods (window, sleep sensors, charging); morning (time, motion, alarm, manual) | `autorules.py`, `night.py` | `test_night_morning.py` | done | |

## 3. Data model

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| Roles home, night, away, vacation, guest, dnd, custom, all_home, all_away; name editable; enabled | `models.py`, `const.py` | `test_models.py::test_role_types_and_kinds`, `test_role_round_trip` | done | |
| Kinds: primary, overlay (brief) | `models.py` | `test_models.py` | deviated | Three kinds: primary, overlay, **derived** (Step 2, amendment 2) |
| Exactly one primary; overlays stack | `engine.py` | `test_engine.py::test_overlays_stack_and_do_not_touch_primary` | done | |
| Up to 10 custom modes, ids `custom_1`.. | `config_flow.py`, `const.py` | `test_config_flow.py::test_options_custom_modes`, `test_options_custom_menu_limits` | done | Amendment 7 |
| enter_actions, exit_actions | `actions.py`, `models.py` | `test_actions.py`, `test_models.py::test_role_actions_roundtrip` | done | |
| `alarmo_mode` per role | `settings.py` (mapping table of the bridge) | `test_alarmo.py::test_to_alarmo_every_mapping` | deviated | The mapping lives in the Alarmo options, not on the role |
| Options: persons, away_delay_min 4, vacation_after_h 24, night, morning, override | `settings.py`, `config_flow.py` | `test_options_step3.py` | done | |
| `permissions` + `guest_users` | `permissions.py` | `test_permissions.py`, `test_options_step3.py::test_user_rules_step_enforces_guest` | deviated | Merged into one `user_rules` model (Step 2, amendment 10) |
| notify, alarmo, vacation_sim options | `settings.py` | `test_options_step4.py` | done | |
| Runtime state restored: primary, previous, since, overlays, override, last_trigger | `coordinator.py`, `models.py` | `test_init.py::test_state_is_restored_after_unload`, `test_models.py::test_state_round_trip_and_corruption` | done | |
| One config entry per household | `manifest.json` (`single_config_entry`) | `test_init.py::test_single_entry_only` | done | |
| Storage and config entry versioned; upgrade from Step 2/3 data | `const.py`, `config_flow.py`, `__init__.py` | `test_lifecycle.py` (upgrade, newer-version refusal) | done | All stores are 1.1; later fields are optional with defaults |

## 4. Pipeline, entities, services, events

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| Pipeline order: permission → priority → role enabled → exit actions → state → enter actions → event → history → notify → Alarmo | `engine.py` | `test_engine.py::test_hooks_run_in_order_and_failures_are_isolated` | done | |
| `home_modes_changed` {from, to, source, rule, user_id} | `engine.py`, `const.py` | `test_engine.py::test_set_primary_applies_and_fires_event`, `test_step3_services.py::test_event_payload_overlay_and_primary` | done | Overlay events add `role` and `active` (Step 3 decision 6) |
| `home_modes_denied` fired and logged | `engine.py` | `test_engine.py::test_denied_fires_event` | done | |
| `select.home_mode` | `select.py` | `test_entities.py::test_select`, `test_entity_ids_and_names` | done | Options are the role names; `role` and `mode_id` attributes |
| `binary_sensor.home_mode_<role>` per enabled role | `binary_sensor.py` | `test_entities.py::test_binary_sensors_and_overlay_switches` | done | all_home / all_away follow live presence |
| `sensor.home_mode_since`, `_previous`, `_trigger_reason` | `sensor.py` | `test_entities.py::test_sensors` | done | |
| `switch.home_mode_auto`, `switch.home_mode_overlay_<role>` | `switch.py` | `test_entities.py::test_auto_switch` | done | |
| Services set_mode, revert, set_temporary, set_auto, set_overlay, import_input_select | `__init__.py`, `services.yaml` | `test_services.py`, `test_step3_services.py`, `test_migration.py` | done | plus `clear_history` (Step 4) |
| Device triggers and conditions | none | n/a | deviated | Decided against (Step 3 answer 1): state triggers/conditions on the role sensors are the supported way; see [research-new-trigger-platform.md](research-new-trigger-platform.md) |
| History log | `history.py` | `test_history.py` | done | capped, delayed save, logbook |
| Assist intent: set the house mode | `assist.py` | `test_intent.py` | done | File is `assist.py`, not `intent.py`. Replies are English only |
| Assist sentences shipped | none | `test_intent.py::test_documented_sentences_work_end_to_end` | deviated | Home Assistant has no mechanism for a custom integration to ship sentences; user file in `docs/examples/` |
| Naming: has_entity_name, translation keys, unique ids, device info | all platforms | `test_entities.py::test_entity_ids_and_names`, `test_user_renamed_entity_name_is_kept` | done | |

## 5. Alarmo and the Ring blueprint

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| Optional, off by default, no hard dependency | `alarmo.py` | `test_alarmo.py::test_disabled_by_default`, `test_alarmo_absent_at_setup`, `test_alarmo_removed_at_runtime` | done | |
| Directions both / to_alarmo / from_alarmo; per-mapping flags | `alarmo.py` | `test_alarmo.py::test_direction_*`, `test_mapping_flags_are_per_direction` | done | |
| Alarmo changes start an override; keypad changes arrive as Alarmo state changes | `alarmo.py` | `test_alarmo.py::test_keypad_change_starts_override_that_survives_presence`, `test_ring_keypad_sequence` | done | Simulated at the Alarmo state level |
| Exit delay respected; failed-to-arm reported | `alarmo.py` | `test_alarmo.py::test_exit_delay_respected`, `test_failed_to_arm_*` | done | |
| Works with the Ring blueprint and without; blueprint unchanged | docs | `test_alarmo.py::test_ring_keypad_sequence` | partly | Tested against a fake Alarmo; **not** a real Alarmo or keypad |
| Docs with sequence diagram, known limitations, real-Alarmo test script | `docs/alarmo-and-ring-blueprint.md`, `docs/real-alarmo-test.md` | n/a | done | |

## 6. Features of Steps 4 and 5

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| Enter/exit actions: order, context parent, timeout, isolation, loop limit | `actions.py` | `test_actions.py` | done | |
| Vacation simulation: random, replay, fallback, only selected lights, restart, off on unload | `vacation.py` | `test_vacation.py`, `test_vacation_recorder.py` | done | Recorder is not a hard dependency |
| Notifications: rules, templates, HM_ channels, platform fields, rate limit, defaults off | `notify.py`, `template_vars.py` | `test_notify.py` | done | Field names per Companion docs; **not** tested on a device |
| Template variables from_role, to_role, from_name, to_name, from_mode, to_mode (role ids) | `template_vars.py` | `test_notify.py::test_variables_are_stable_when_renamed`, `test_from_is_not_available` | done | `from` is reserved |
| Suppressed notifications write a history entry | `notify.py` | `test_notify.py::test_suppressed_messages_are_never_silent` | done | |
| Frontend cards (full and guest), no build, no external requests, visual editors | `frontend/home-modes-cards.js`, `frontend.py` | `test_frontend.py`, `tests/js/cards.test.mjs` | partly | Logic checked with jsdom; real rendering, themes, iOS and Android are **not** tested |
| `home_modes/allowed_roles` websocket command | `ws.py` | `test_guest_dashboard.py` | done | |
| Migration helper and optional mirror (with overlay option) | `migration.py`, `mirror.py`, `config_flow.py` | `test_migration.py`, `test_safety_claims.py::test_import_with_a_full_mapping_but_no_confirm_writes_nothing`, `test_mirror.py` | done | Import saves only the import; hard-coded English labels in the import flow |
| Diagnostics with redaction | `diagnostics.py` | `test_diagnostics.py` | done | |
| Companion app notes | `docs/companion-apps.md` | n/a | partly | Widget and tile support for scripts is UNVERIFIED |
| Per-role button entities | none | n/a | deviated | Decided no (Step 5 answer 1) |

## 7. Quality, CI, docs, repo

| Requirement | Implemented in | Test | Status | Notes |
|---|---|---|---|---|
| pytest with the HA custom component plugin, above 90 % coverage | `tests/`, `pytest.ini`, `tests.yml` (`--cov-fail-under=90`) | full suite | done | 98 % |
| hassfest and HACS validation in GitHub Actions | `validate.yml` | `test_release_files.py::test_workflows_follow_the_ci_rules` (static) | partly | **Never run on GitHub**; only the dependency check of hassfest ran locally |
| tests.yml: ruff, mypy, JS, matrix 2026.10.4 required / 2026.11.1 best effort, Python 3.14 (latest patch) | `tests.yml` | static test above; the steps were reproduced locally with equivalent virtual environments | partly | See "Not run" below |
| 10x load/unload/reload leak test | `tests/test_lifecycle.py` | itself | done | `engine.async_stop` is not detected by the leak test |
| Upgrade test; removal test | `tests/test_lifecycle.py` | itself | done | Recorder history stays until the recorder purges it; nothing of ours stays |
| Release workflow; release script; first tag v0.9.0 pre-release | `release.yml`, `.github/scripts/release_info.py` | `test_release_files.py::test_release_script_*` | partly | Script tested; the workflow itself never ran |
| README with community notice, why, features, install, quick start, screenshot placeholders, status, security notes, Companion push note | `README.md` | `test_release_files.py::test_every_doc_is_linked_from_the_readme` | done | |
| CHANGELOG, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue and PR templates | repository root, `.github/` | `test_release_files.py` | done | Private vulnerability reporting must be enabled in the repository settings |
| Brand images | `custom_components/home_modes/brand/` | `test_release_files.py::test_brand_images_have_the_documented_sizes` | partly | **Placeholders**; must be replaced |
| Blueprints (three, roles, rename-proof, import links) | `blueprints/automation/home_modes/` | `tests/test_blueprints.py`, `test_release_files.py::test_blueprint_import_links_in_the_docs_are_correct` | done | The brief asked for one example; three delivered |
| Docs: configuration, priority/override, Alarmo, guest, migration, examples, security, translations, release checklist, research, community post | `docs/` | `test_release_files.py::test_every_doc_is_linked_from_the_readme` | done | |
| This audit only cites files, symbols and tests that exist | `docs/final-audit.md` | `test_audit_references.py::test_every_reference_in_the_audit_exists` | done | Wrong or missing references fail the tests |
| Smoke test script and publishing guide | `docs/smoke-test.md`, `docs/publishing-guide.md` | `test_release_files.py::test_every_doc_is_linked_from_the_readme` | partly | Scripts written; neither has been followed on a real instance or GitHub |
| Repo layout doc matches the tree | `docs/repo-layout.md` | `test_release_files.py::test_repo_layout_doc_matches_the_tree` | done | |
| Repo layout of the brief (file names) | see layout doc | n/a | deviated | `migration.py` (brief: `migrate.py`), `assist.py` (brief: `intent.py`); no `device_trigger.py`, `device_condition.py`, `strings.json`; additional modules `autorules.py`, `settings.py`, `mirror.py`, `ws.py`, `frontend.py`, `logbook.py`, `template_vars.py` |
| strings.json and translations/en.json | `translations/en.json` | `hassfest` (not run) | deviated | Custom integrations load `translations/en.json`; `strings.json` dropped (Step 2, amendment 4) |
| Manifest: integration_type service, iot_class calculated | `manifest.json` | hassfest (not run on GitHub) | deviated | Kept by decision, see [integration-type.md](integration-type.md) |

## 8. "No cloud, no external dependencies": the scan

Commands and results (run in the repository at version 0.9.0):

- `manifest.json`: `"requirements": []`.
- Python, an AST scan of every module in `custom_components/home_modes/` for imports of
  `socket`, `urllib`, `http.client`, `requests`, `aiohttp`, `httpx`, `ftplib`, `smtplib`,
  `telnetlib`, `websockets`, `subprocess`, `pickle`, `ssl`, calls of `eval`, `exec`,
  `compile`, `__import__`, and use of `async_get_clientsession` / `async_create_clientsession`:
  **no match**. This is a test (`test_python_has_no_network_or_dynamic_code`).
- A `grep` for the same names plus `urlopen`, `os.system`: **no match**.
- JavaScript (`frontend/home-modes-cards.js`): no `fetch`, `XMLHttpRequest`, `WebSocket(`, `sendBeacon`,
  `import(`, `eval`, `new Function`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`, `http://`, `https://`, cookies or storage. This is a test
  (`test_js_has_no_risky_patterns`).
- What the integration does call: Home Assistant's own services (for example `notify.*`,
  `light.turn_off`, `alarmo` services, `input_select.select_option`), the recorder, and Home
  Assistant's websocket from the cards (through the `hass` object). Whatever those services do
  (for example Companion app push through Apple and Google) is outside this integration and is
  stated in the README.
- Limit of the scan: it proves the absence of network code in this repository. It cannot prove
  what another integration does when we call its service.

## 8b. Mutation checks (final verification pass)

Each rule below was broken on purpose in the source, the listed tests were run, and the source was restored.
All 14 mutations made at least one test fail ("caught"). One was **not** caught at first and the tests were strengthened.

| Rule | Mutation | Caught by |
|---|---|---|
| Role permission (pure check) | allow-list ignored | `test_guest_dashboard.py::test_allowed_roles_per_user` |
| Role permission (service/entity path) | allow outside the list | `test_permissions.py::test_role_permissions` |
| Auto switch denied to allow-list users | allowed | `test_permissions.py::test_auto_control_permissions` |
| Unknown user denied (fail closed) | allowed | `test_permissions.py::test_role_permissions` |
| `allowed_roles` websocket | returns everything | `test_guest_dashboard.py::test_allowed_roles_per_user` |
| History hidden from guests | visible | `test_history.py::test_websocket_permissions` |
| Alarmo: no disarm without `allow_disarm` | check removed | `test_alarmo.py::test_never_disarms_by_default` |
| Alarmo: auto-rule changes do not arm | gate removed | `test_alarmo.py::test_auto_rule_changes_do_not_touch_alarmo` |
| Alarmo: restricted users cannot disarm | check removed | `test_alarmo.py::test_disarm_blocked_for_allow_list_user` |
| Alarmo: origin guard | removed | `test_alarmo.py::test_startup_reconcile_never_touches_alarmo` |
| Alarmo: echo detection | removed | **not caught at first** (an echo to the same role is a no-op); now `test_safety_claims.py::test_late_echo_of_our_own_arming_does_not_flip_the_mode_back` |
| Alarmo: `code_required` guard | removed | `test_alarmo.py::test_code_required_is_reported_never_stored` |
| Failures never block a change | hook failure re-raised | `test_engine.py::test_hooks_run_in_order_and_failures_are_isolated` |
| Import needs confirm | always applies | `test_migration.py::test_service_preview_writes_nothing` |

**Not mutation-checked:** the mirror's one-direction and loop guard, the action loop limit,
the guest card's narrowing in JavaScript, the permission check inside the Assist intent and the
history/diagnostics redaction. These have tests, but I did not show that the tests fail when the rule is removed.

## 9. Deviations and UNVERIFIED items, grouped

### Must test before 1.0

1. A real Alarmo (and the Ring keypad blueprint): every direction, exit delay, failed to arm, no echo, no disarm by default. The documented behaviour of Alarmo (state names, services, context handling) was implemented from its docs and source and tested with a fake.
2. The GitHub workflows: hassfest, the HACS action, lint, tests, the release workflow, `gh release create`, the pinned action major versions, Python 3.14 (resolved to the latest patch) on the runner and the pip and npm caches.
3. HACS: which version is offered for a pre-release; the Marketplace install on a real 2026.11 instance.
4. iOS and Android Companion apps: notification fields (interruption level, channels), cards, shortcuts, widgets.
5. A real non-admin guest account on a real guest dashboard; what the account can see and do; which voice clients send a user id to Assist.
6. Migration from a real `input_select` with real automations.
7. A real time zone change and a real DST change with a night timer armed.
8. Brand images replaced with real artwork.
9. The card visual editors and the cards in light and dark themes on real browsers.

### Can ship in beta

1. Android widgets and quick-settings tiles for scripts; CarPlay and watch use (UNVERIFIED which are supported).
2. The UI label of the Lovelace dashboard "require admin" option (the field exists and defaults to false in the source).
3. Raspberry Pi performance (reasoned, not measured).
4. `engine.async_stop` is not covered by the leak test.
5. Best-effort status of Home Assistant 2026.11.x in CI (the test plugin targets 2026.10.4; a small shim is used).
6. The floating references `home-assistant/actions/hassfest@master` and `hacs/action@main` (floating by their documented design).
7. English-only strings: import flow labels, default role names, Assist replies, history rule names (listed in [translations.md](translations.md)).
8. Alarmo setups that require a code to arm: Home Modes records `code_required` and does not arm.

### Nice to have (recommendations, not built)

1. A trigger platform (a `trigger.py` platform): technically usable by custom integrations (a spike worked on both versions), but the API is young; revisit after it stabilises ([research note](research-new-trigger-platform.md)).
2. Device triggers and conditions: not built by decision.
3. Per-role button entities: not built by decision.
4. Translations beyond English once the import flow strings move into `translations/en.json`.
5. Dark brand images; real screenshots.
6. Making `home_modes_changed` payload also available as a typed trigger.
7. A `docs/` page with real measurements (memory, CPU) after the Raspberry Pi test.
8. A bundled Assist response file once Home Assistant supports shipping sentences from custom integrations.

## 10. Risks, by severity

| # | Severity | Risk | Mitigation now | Remaining action |
|---|---|---|---|---|
| 1 | High | Nothing has run on a real Home Assistant, Alarmo, or phone. An assumption about a real device may be wrong | Beta label, honest status table, fake Alarmo built from the documented interface | Release checklist, items under "must test" |
| 2 | High | The guest model is not a security boundary: HA has no per-service permissions; automations are trusted | Server-side checks for what the integration controls; security notes in README and guest docs; tests including scripts | Users must follow the recommendations; nothing more is possible in the integration |
| 3 | Medium | Alarmo bridge behaviour with real Alarmo timing (exit delay, state names) differs from the fake | Safety defaults (no disarm, no auto-arming), loop guard with expected-state suppression | Real Alarmo test script |
| 4 | Medium | The CI has never run on GitHub; pinned action versions were taken from release pages and could not be confirmed on a runner | Workflows reviewed; steps reproduced locally in equivalent environments | Run once, fix |
| 5 | Medium | Distribution: HACS pre-release behaviour and the Marketplace are unverified | Documented install paths | Test v0.9.0 via a custom repository |
| 6 | Medium | Auto-rule behaviour surprises users (next_auto, vacation timers, expiry re-evaluation) | Detailed rules and a decisions table | Feedback from testers |
| 7 | Medium | CI Python version: Python 3.14.2 exactly makes one test (`test_vacation_recorder.py`) error in its fixture; HA requires only >=3.14.2. Found in the clean run | CI now uses `3.14` (latest patch); 3.14.6 passes | Confirm the runner resolves `3.14` and the job is green |
| 8 | Low | The card's real rendering and the visual editors may break on a Home Assistant frontend change | Uses standard `ha-*` elements and CSS variables; jsdom checks | Manual checklist |
| 9 | Low | Brand images are placeholders | Tests check the sizes; release checklist | Replace |
| 10 | Low | 2026.11.x relies on a test shim | Best-effort job, `continue-on-error` | Drop the shim when the plugin supports 2026.11 |
| 11 | Low | Missed during development: the card's version constant lagged behind the manifest | Now covered by `test_frontend.py::test_js_version_matches_the_manifest` | None |
| 12 | Low | Raspberry Pi load unknown | Event-driven design, delayed saves, capped history | Measure |
| 13 | Low | English-only parts | Listed in translations.md | Move strings to `translations/en.json` later |

## 11. Recommendation

- **Public beta (v0.9.0 as a GitHub pre-release): GO**, with these conditions before announcing:
  1. Replace the brand placeholders (or accept visible placeholders for the beta and say so).
  2. Enable private vulnerability reporting, Issues, topics and the description.
  3. Run the workflows once on GitHub and fix what they report.
  4. Do a smoke install on a real instance (fresh install, both presets, one automation, the card).
  5. Say clearly in the post what has not been tested (the draft does).
- **1.0.0: NO-GO** until the "must test before 1.0" list is done and the beta feedback is handled.
