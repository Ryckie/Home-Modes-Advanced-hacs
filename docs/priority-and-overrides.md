# Priority and override rules

Every mode change goes through one pipeline (`engine.py`). This page describes how competing
sources are ranked and how manual overrides work. The rank table lives in one constant,
`SOURCE_RANKS` in `custom_components/home_modes/models.py`.

## Source ranks

| Rank | Name      | Sources                                                                                                                        |
| ---- | --------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 1    | manual    | UI (select, switches), services called by a user, Assist/voice, Alarmo-originated changes (Step 4), `temporary_expiry` reverts |
| 2    | schedule  | night time window, morning time                                                                                                |
| 3    | sensor    | sleep sensors, phone charging, morning motion, morning alarm                                                                   |
| 4    | presence  | away, vacation, all_home, all_away auto-rules                                                                                  |

`system` (rank 0) is internal housekeeping (first start, a disabled active role) and always
applies.

A higher rank (lower number) always wins. While an override is active, every source with a
lower rank than the override's source is ignored.

## Within one evaluation

When several auto-rules would fire at once (for example at startup, after `set_auto` or when
the auto switch is turned on) the rules are evaluated in rank order and the first one that
changes the mode wins; the others are not applied in the same pass. If schedule and presence
fire together, schedule wins. A rule is skipped (not rejected) when its target role is
disabled.

## Overrides

A manual change **by a user** (the call carries a `user_id`) starts an override. The option
`override.until` decides how it ends:

| `until`      | The override ends...                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------- |
| `next_auto`  | (default) when the next auto-rule trigger of any rank would fire. That rule then applies.                     |
| `end_of_day` | at the next local midnight. Auto-rules are then re-evaluated.                                                 |
| `duration`   | after `override.duration_min` minutes. Auto-rules are then re-evaluated.                                      |
| `set_auto`   | only when the `home_modes.set_auto` service is called (or an admin clears it by calling it).                  |

"Would fire" for `next_auto` means the rule's guard passes: for example the night rules do
not fire while the mode is Away or Vacation, so such a trigger does not end the override.

Calls without a user (automations, scripts without a user context, the system) rank as
manual but start **no** override, unless the call sets `override: true`. A user's call can set
`override: false` to opt out. `set_mode` has the optional boolean field `override`:

| Caller            | `override` omitted | `override: true` | `override: false` |
| ----------------- | ------------------ | ---------------- | ----------------- |
| user              | override starts    | override starts  | no override       |
| no user           | no override        | override starts  | no override       |

Overlays (Guest, Do not disturb) never start an override. Changing the mode again while an
override runs replaces the override (if the new change starts one) or leaves it as it is.

All override and temporary-mode end times are stored as absolute timestamps.

## Temporary modes

`set_temporary(mode, duration)` changes the mode (rank 1, source `manual`, rule `temporary`),
remembers the mode it came from and reverts to it when the duration ends (rank 1, source
`temporary_expiry`). While it runs, auto-rules are ignored (it creates a timed override).

- A second `set_temporary` during a running one keeps the **original** revert target.
- Any other primary change (manual or system) cancels the pending revert.
- If the revert target is no longer an enabled primary-kind mode, the first enabled primary-kind
  mode is used. Derived modes (all_home, all_away) are never used as a fallback.
- After the revert the auto-rules are re-evaluated immediately (unless the auto switch is off). If
  presence or time now say another mode applies, that mode is applied with the normal ranks (and
  the normal delay logic): leaving during a temporary Night ends in Away, not Home.

`revert` goes back to the previous primary mode (manual change, rule `revert`). Calling it
repeatedly toggles between the last two modes. After a revert the auto-rules are re-evaluated
immediately (unless the auto switch is off). `set_auto` clears the override and
re-evaluates the auto-rules immediately (only when the auto switch is on).

## Auto switch

`switch.home_mode_auto` off disables all auto-rules. Turning it on re-evaluates them
immediately. Only admins and unrestricted users can toggle it; allow-list users cannot.

## Rules

### Presence

- Tracked persons are set in the options. `all_home` is true when every tracked person is
  `home`, `all_away` when every tracked person is away. Any known state other than `home`
  (`not_home` or a zone name) counts as away.
- **Unknown and unavailable states are "not changed":** the last known status of that person
  is kept and nothing is triggered. A person that was never known counts for neither signal;
  the binary sensors report `unknown` until every person is known (`off` as soon as one known
  person contradicts the signal).
- When all persons are away, a timer starts (`all_away_since`, stored as an absolute time).
  After `away_delay_min` (default 4) the mode becomes **All away** if that role is enabled,
  else **Away**. After `vacation_after_h` (default 24) of continuous all-away the mode becomes
  **Vacation** (only if enabled).
- When a person arrives while the mode is Away, All away or Vacation, the mode becomes **Home**
  (only if Home is enabled) and the timers are cancelled.
- All home: from **Home** to **All home** when everybody is home (role enabled); back to
  **Home** when somebody leaves.

### Night

Any combination of methods. Rules only fire from Home, All home and custom modes (never from
Away, Vacation or All away).

- **Time window** (schedule): at the window start, if the mode changed before the window began.
- **Sleep sensors** (sensor): a sensor turns `on`.
- **Phone charging** (sensor): a charging sensor turns `on` (`on` or `charging`) while the time
  is inside the night window.
- **Manual**: no auto-rule.

### Morning

Rules only fire while the mode is Night and end it with **Home** (only if Home is enabled).

- **Time** (schedule): at the morning time.
- **Motion** (sensor): a motion sensor turns `on`, from the *earliest* time until the night
  window start (so evening motion does not count).
- **Alarm** (sensor): the next-alarm timestamp sensor reaches its time.

## Restart behaviour

Timers are derived from stored absolute timestamps and the options, and re-armed at startup.
Whatever expired while Home Assistant was down is applied once, in this order: expired
temporary mode (revert), expired override (cleared), then one evaluation of all auto-rules in
rank order. This evaluation is level-based, so a rule whose condition is still true at
startup (for example night window active and the mode changed before it began) applies.

## Time zones, DST and clock changes

All timers are stored as absolute UTC instants and re-armed at startup, so they are not
shifted by DST. Night and morning times are *local* times, converted to UTC when armed.

| Situation | Behaviour |
|---|---|
| A local time that does not exist (spring forward) | maps to one instant (the transition) |
| A local time that occurs twice (fall back) | maps to its first occurrence |
| Duration overrides and temporary modes | count real elapsed time, also across DST |
| `end_of_day` on a 23 or 25 hour day | ends at the next local midnight |
| Time zone changed in Home Assistant | timers are re-armed immediately and the rules are evaluated |
| Clock jumps back | overrides keep their stored absolute end |
| Clock jumps forward | everything that became due is applied once, in rank order |
| Night rule | fires only if the current mode began before the last window start |

Proof: `tests/test_time_changes.py`.

## Decisions where the brief was silent

| Topic | Decision |
| ----- | -------- |
| Person in a zone (for example "work") | Counts as away. Only `home` counts as home. |
| Unknown / unavailable person state | "Not changed": last known status kept, nothing triggered. A never-known person counts for neither signal. |
| All home ends | When somebody leaves, All home goes back to Home. |
| Away target | All away if that role is enabled, otherwise Away. |
| Vacation | Only from continuous all-away, only if the Vacation role is enabled. |
| Night rules leave from | Home, All home and custom modes only. Never from Away, Vacation or All away. |
| Morning rules need | Mode Night; target Home (skipped if Home is disabled). |
| Morning motion | Counts from the *earliest* time until the night window start. |
| Phone charging | Counts only inside the night window. |
| Night window | Fires once at the window start; it never ends Night (the morning methods do). |
| Disabled rule target | The rule is skipped, it does not fail and does not end a `next_auto` override. |
| Evaluation order | Rank order; the first rule that changes the mode wins the pass. |
| Nested `set_temporary` | Keeps the first revert target. |
| Manual change during a temporary mode | Cancels the pending revert. |
| After temporary expiry / revert | Auto-rules are re-evaluated immediately (unless the auto switch is off). |
| `set_auto` with the auto switch off | Clears the override, does not evaluate. |
| Zero or negative `set_temporary` duration | Rejected. |
| Level-based evaluation | At startup, after `set_auto`, when auto is switched on and after override expiry, rules whose condition is currently true apply (once). |
| Overlays | Never start an override. |

## Known limitation

Changes made by an automation carry no user, so they are unrestricted and start no override.
An automation that a guest triggers therefore runs with full rights.
