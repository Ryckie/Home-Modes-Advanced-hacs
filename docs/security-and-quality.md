# Security and quality review

Scope: version 0.9.0. Everything below was checked against the source in this repository;
the "Proof" column names the test that fails if the behaviour changes. Items that could not
be verified without a real device or a real Alarmo are listed in
[release-checklist.md](release-checklist.md).

TL;DR

- Every mode change goes through one server-side permission check; nothing relies on the cards.
- Admins and calls without a user id (automations, the system) are trusted; this is a Home
  Assistant limit, see "Known limits".
- No network code in the Python or the JavaScript; no secrets are stored or logged.
- All timers and listeners are released on unload (10x reload test).
- DST and clock-jump handling is tested; two real bugs were found and fixed while writing the tests.

## 1. Permissions matrix

Rule model: `user_rules {user_id: {mode: allow_list | unrestricted, roles: [...]}}`. Users that
are not listed are unrestricted. Administrators are always allowed. A call with no user id is
allowed (trusted). Home Assistant's own "who can open the options dialog" rule (admins only)
protects the configuration.

| Interface | Who may call it | Check | Proof |
|---|---|---|---|
| Service `home_modes.set_mode` | admin, unrestricted user, allow-list user for roles on the list, no user | role check (`permissions.async_check_role`) | `test_services.py::test_service_enforces_permissions`, `test_permissions.py::test_role_permissions` |
| Service `home_modes.set_overlay` | same, per overlay role | role check | `test_services.py::test_service_enforces_permissions`, `test_guest_dashboard.py::test_guest_cannot_bypass_the_card` |
| Service `home_modes.set_temporary` | same, per target role | role check | `test_step3_services.py::test_permission_denial_on_new_services` |
| Service `home_modes.revert` | same, per role that would be restored | role check on the target | `test_step3_services.py::test_permission_denial_on_new_services` |
| Service `home_modes.set_auto` | admin, unrestricted user, no user; **not** allow-list users | auto-control check | `test_step3_services.py::test_permission_denial_on_new_services`, `test_permissions.py::test_auto_control_permissions` |
| Service `home_modes.clear_history` | admin only (`async_register_admin_service`) | Home Assistant | `test_history.py::test_clear_history_admin_only` |
| Service `home_modes.import_input_select` | admin only | Home Assistant | `test_migration.py::test_service_is_admin_only` |
| `select.home_mode` (select option) | as `set_mode`; the user's context is passed through | role check | `test_entities.py::test_permission_denied_surfaces_as_error` |
| Overlay switches | as `set_overlay` | role check | `test_entities.py` (overlay switches), `test_guest_dashboard.py` |
| `switch.home_mode_auto` | as `set_auto` | auto-control check | `test_permissions.py::test_auto_control_permissions` |
| Websocket `home_modes/history` | any logged-in user; admins see everything, other users see mode changes and their own denied attempts (no system entries, no action failures or bridge notes), allow-list (guest) users see none | filtered in `History.visible_entries` | `test_history.py::test_websocket_permissions` |
| Websocket `home_modes/allowed_roles` | any logged-in user; returns only the caller's own list and only id, name, type, icon | pure function of the caller | `test_guest_dashboard.py::test_allowed_roles_per_user`, `test_allowed_roles_never_leaks_other_users_or_actions` |
| Assist intent `HomeModesSetMode` | the user of the conversation; an allow-list user is checked; no user means trusted | role check | `test_intent.py::test_intent_enforces_permissions` |
| Assist intent `HomeModesSetOverlay` | as above | role check | `test_intent.py::test_intent_enforces_permissions` |
| Scripts a user starts | keep the user id, so the user's limits apply | context | `test_services.py::test_context_propagates_through_scripts`, `test_guest_dashboard.py::test_script_started_by_a_guest_keeps_the_guests_limits` |
| Automations | lose the user id and are trusted | context | `test_services.py::test_context_is_lost_through_automations` |
| Alarmo disarm through the bridge | blocked for allow-list users | permission plus per-mapping "allow disarm" | `test_alarmo.py::test_disarm_blocked_for_allow_list_user` |
| Options flow (all screens, import) | Home Assistant admins | Home Assistant | `test_config_flow.py`, `test_options_step3.py`, `test_migration.py` |

Denied attempts are logged to the history, fired as `home_modes_denied` and can notify
(`test_engine.py::test_denied_fires_event`, `test_intent.py::test_intent_denied_attempts_are_in_the_history`).

### Known limits (not closable by this integration)

Home Assistant has no per-service permission for non-admin users. A non-admin user can call
any service the API allows, an automation runs without a user, and a guest can trigger an
automation that sets a mode. Treat guest accounts as lower-trust, not as a security
boundary. See the "Security notes" section of [guest-dashboard.md](guest-dashboard.md).

## 2. Input validation

| Input | Validation |
|---|---|
| `set_mode.mode` | string, resolved against the configured roles; unknown, disabled or wrong-kind ids are rejected with a translated error (`test_engine.py::test_unchanged_unknown_disabled_and_invalid`) |
| `set_mode.override` | boolean |
| `set_overlay.overlay` / `active` | string resolved to an overlay role / boolean |
| `set_temporary.mode` / `duration` | string / time period that must be greater than zero |
| `import_input_select.entity_id` | valid entity id; must be an existing `input_select` (`test_migration.py`) |
| `import_input_select.mapping` | mapping of strings; every target role must exist |
| `import_input_select.confirm`, `mirror`, `mirror_overlays` | booleans; the import writes nothing unless `confirm` is true |
| Websocket `home_modes/history.limit` | integer from 1 to 500 (`vol.Range`), default 50 |
| Websocket `home_modes/allowed_roles` | no parameters |
| Assist slots | `name` slot validated by the intent helper; unknown roles answer "no valid target" (`test_intent.py`) |
| Options flow fields | selectors with limits; role names unique (case-insensitive); at least one primary enabled; numeric ranges clamped when parsed (`settings.py`); history size clamped to 10–5000 |
| Stored data | parsed defensively; invalid roles are skipped and logged by id only; corrupt state starts fresh; a newer major storage version is refused without touching the files (`test_lifecycle.py`) |
| Notification templates | rendered with Home Assistant's `Template`; a failing template falls back to the default text (`test_log_privacy.py`) |

## 3. Frontend

File: `custom_components/home_modes/frontend/home-modes-cards.js` (one file, no build step).

| Check | Result | How it was checked |
|---|---|---|
| No unescaped rendering | Text is set with `textContent` / `setAttribute`; the file never assigns `innerHTML`, `outerHTML` or `insertAdjacentHTML` | scan for those names (only a comment mentions `innerHTML`); `tests/js/cards.test.mjs` |
| No `eval` | No `eval`, `new Function`, `document.write`, string timers or dynamic `import()` | scan |
| No external requests | No `fetch`, `XMLHttpRequest`, `WebSocket(`, `sendBeacon`; no `http(s)://` URL in the file; the cards use only the `hass` object they are given | scan |
| No secrets or storage | No cookies, `localStorage` or `sessionStorage`; no tokens | scan |
| Server remains the authority | The guest card only filters buttons by `home_modes/allowed_roles`; the services check again | `test_guest_dashboard.py::test_guest_card_config_cannot_widen_server_list` |

The scan is automated in `tests/test_frontend.py::test_js_has_no_risky_patterns`. The Python side
(no network, subprocess, `eval`/`exec` or pickle) is automated in
`tests/test_release_files.py::test_python_has_no_network_or_dynamic_code`.

## 4. Logging

Rules: no secrets, codes, full notification targets or message bodies at any level.

- The integration stores no Alarmo code and logs none.
- Notification targets are shortened (`mobile_a…`); on a failure only the exception class name is
  logged, never its text (the text can repeat the message).
- Template failures log the exception class name only.
- Vacation light failures log the entity id and the exception class name.
- Action failures keep the error text in the (admin-only) history, limited to 200 characters;
  the log line also carries it, because it is the user's own action that failed.
- Denied changes log the user id and the reason, not the user name.
- Role definitions that fail to load are logged by id only.

Proof: `tests/test_log_privacy.py` runs a failing notify service whose error text repeats the
message body and a code, a denied guest and a broken template at DEBUG, and asserts that none
of the three strings appear in any record of this integration. While writing it, a DEBUG
traceback that repeated the error text was found and removed.

Not covered: Home Assistant core logs a failing foreign service with its own traceback. That
is outside this integration.

## 5. Resource use

| Area | Behaviour |
|---|---|
| Listeners | one state listener for tracked persons, one for sensors used by rules, one for the optional input_select mirror, one for the Alarmo entity, one `EVENT_CORE_CONFIG_UPDATE` listener; all removed on unload (`test_lifecycle.py`, 10x reload) |
| Timers | `async_track_point_in_utc_time` only: away delay, vacation, night/morning, override end, temporary expiry, vacation simulation. No polling loops. Each timer is rebuilt from absolute timestamps |
| Store writes | `Store.async_delay_save` (1 s) for state, history and vacation data; immediate save on unload. A burst of changes becomes one write |
| History | in memory and in one store, capped at 500 entries by default (10–5000) |
| Recorder | used only by the replay strategy of the vacation simulation: one query per planned day, in the recorder's executor, for the selected lights only; not a hard dependency |
| Startup | no I/O beyond reading three small stores; expired timers are applied once in rank order |
| Raspberry Pi | nothing computationally heavy; the largest items are the recorder query (selected lights, one day) and the JavaScript file served once (about 20 KB). Not measured on a real Pi (UNVERIFIED) |

## 6. Failure modes

| Situation | Behaviour | Proof |
|---|---|---|
| Alarmo not installed at setup | integration works, bridge waits and logs one info line | `test_alarmo.py::test_alarmo_absent_at_setup` |
| Alarmo removed at runtime | bridge stops without errors, modes keep working | `test_alarmo.py::test_alarmo_removed_at_runtime` |
| Alarmo never disarmed automatically | requires a per-mapping "allow disarm"; auto-rules need "apply auto rules" | `test_alarmo.py::test_apply_auto_arms_but_never_disarms_without_switch` |
| Recorder missing or empty | replay falls back to random, one warning | `test_vacation.py::test_replay_without_recorder_falls_back`, `test_replay_falls_back_to_random_without_history` |
| Frontend / HTTP missing | cards are not served or loaded; the integration still works | `test_frontend.py::test_works_without_the_frontend` |
| Notify target missing or failing | isolated, logged without details, other targets and the change unaffected | `test_notify.py::test_failing_notification_is_isolated`, `test_failure_modes.py::test_missing_notify_service_is_isolated` |
| Person entity removed or unavailable | counts as "not changed"; no away, no arrival | `test_presence.py::test_unknown_and_unavailable_do_not_trigger`, `test_failure_modes.py::test_removed_person_entity_does_not_change_the_mode` |
| Role deleted or renamed | a stored active role that no longer exists falls back to a primary; calls naming it fail cleanly | `test_init.py::test_restored_removed_role_falls_back`, `test_failure_modes.py::test_action_that_targets_a_deleted_role_is_rejected` |
| Action fails or hangs | per-action timeout (30 s default), failure in the history, mode change unaffected | `test_actions.py` |
| Action loop | rate-limited and logged | `test_actions.py` |
| Time zone change | timers are re-armed (`EVENT_CORE_CONFIG_UPDATE`) | `test_time_changes.py` |
| DST | night window computed in local time converted to UTC; a skipped time maps to one instant, an ambiguous time to its first occurrence; duration overrides count real time | `test_time_changes.py` |
| Clock jumps | backwards: overrides keep their stored absolute end; forwards: everything due is applied once in rank order | `test_time_changes.py` |
| Newer storage or config entry version | setup refused, files untouched | `test_lifecycle.py` |
| Corrupt state file | starts fresh with a warning | `test_lifecycle.py` |

### Bugs found by the Step 6 tests

1. `night.py`: comparing two aware datetimes in the same time zone ignores the UTC offset. In
   the repeated hour at the end of DST the next occurrence could be in the past, which would
   re-arm a timer immediately and repeatedly. Fixed by converting to UTC before comparing.
2. `autorules.py`: a time zone change did not re-arm the schedule timers. Fixed with a
   `EVENT_CORE_CONFIG_UPDATE` listener.

## 7. What is not covered

- No test runs against a real Home Assistant instance, a real Alarmo, or a real phone.
- The engine's own `async_stop` is not detected by the leak test (it has no deferred tasks at
  that point).
- Raspberry Pi performance is reasoned, not measured.
