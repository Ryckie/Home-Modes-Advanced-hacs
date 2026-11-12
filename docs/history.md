# History log

Persistent log of mode changes, denied attempts and system events. Stored in
`.storage/home_modes.<entry_id>.history` with a delayed save (about 1 s) and written
immediately when the integration unloads. Default size 500 entries (Options → Integrations →
History log, 10–5000); the oldest entries are dropped first.

## Entry

| Field | Meaning |
| --- | --- |
| `ts` | ISO timestamp (UTC) |
| `kind` | `primary`, `overlay`, `denied`, `system` |
| `from`, `to` | role ids (`null` where not applicable; overlays: `to` is `null` when switched off) |
| `role`, `role_name` | the role concerned |
| `source`, `rule` | where the change came from; for `denied` the rule is the reason; for `system` the event name (`vacation_sim_start`, `vacation_sim_stop`, `action_loop_blocked`, `bridge_error`, `bridge_note`, `notification_suppressed`, `mirror_failed`) |
| `user_id`, `user` | the user, if any |
| `action_failures` | list of `{role, phase, index, error}` for failed or timed-out actions |
| `bridge` | notes of the Alarmo bridge (`{"alarmo": "requested:armed_away"}`, `{"error": "code_required", ...}`) |

## Logbook

`home_modes_changed` and `home_modes_denied` are described in the logbook, attached to
`select.home_mode`: for example *"changed from Home to Night (source: schedule, rule:
night_window)"*, *"Guest turned on (source: manual)"*, *"denied change of Away (reason:
not_in_allow_list)"*. Role names are looked up at display time, so renamed modes show their
current name.

## Service

`home_modes.clear_history`: deletes all entries. **Administrators only** (calls without a user,
such as automations, are allowed like for every Home Assistant admin service).

## Websocket

`{"type": "home_modes/history", "limit": 50}` (limit 1–500, default 50) returns
`{"entries": [...]}`, newest first. Any logged-in user may call it; it is read-only.

| User | Sees |
| --- | --- |
| Administrator | everything, including action failures and bridge notes |
| Normal user | mode and overlay changes, and their own denied attempts; no system entries, no failures or bridge notes |
| Allow-list user (guest) | nothing |

The filtering happens on the server.
