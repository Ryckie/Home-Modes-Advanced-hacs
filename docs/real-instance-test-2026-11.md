# Real-instance test, November 2026

The "must test before 1.0" items that do not need a phone, run on a real Home Assistant
**2026.11.1** (Docker, Python 3.14.10) with **Alarmo** installed, on 2026-11-13. Every step was
driven through Home Assistant's own REST and websocket API (the calls the UI makes), with a
real admin user, a real non-admin guest user and a real non-admin family user.

Test persons were real `person` entities, each tracked by a template device tracker that an
input boolean ("Anna home", "Ben home") moves in and out of `zone.home`. Alarmo had a real
door sensor (template binary sensor) in all armed modes, an exit delay of 8 s for Away and
an entry delay of 10 s.

| Area | Checks | Result |
|---|---|---|
| Fresh install: both presets, single entry, rename/duplicate/last primary/disable active mode/custom mode | 21 | pass |
| Options flow: save per screen, Back on every picker, filtered entity lists, flow survives the reload | 33 | pass |
| Guest account: allow-list for set_mode, select, set_temporary, revert, set_auto, Auto switch, overlays, clear_history, history websocket, allowed roles | 20 | pass (after fix 2 below) |
| Migration from a real input_select: suggestions, preview, usage report (automation + script), decline, confirm, mirror, mirror overlays, renamed option -> `mirror_failed` | 17 | pass |
| Presence: All home / All away, away delay (nothing before, change after), return before the delay, unknown/unavailable never count, arrival, next_auto override, Auto switch, Away without All away | 24 | pass |
| Night and morning: time window, sleep sensor (input boolean), phone charging (in and outside the window, binary sensor and Companion-style battery state), never from Away, morning time, motion (before earliest, after night start, in between), next alarm, disabled target | 22 | pass |
| Overrides: duration, until set_auto, end of day (local midnight), `override: false` | 6 | pass |
| Restarts: change right before the restart action, override end kept and on time, temporary expiring while stopped (reverts once at startup), all away during a 25 h outage -> Vacation, Vacation disabled -> stays away | 14 | pass |
| Time zone change with an armed night timer (Bucharest -> Amsterdam and back) | 5 | pass |
| Real Alarmo, all sections of [real-alarmo-test.md](real-alarmo-test.md) except the Ring keypad | 44 | pass (after fix 1 below) |

## Fixed because of this test

1. **Alarmo failed to arm after the exit delay.** Alarmo writes the previous state back
   *before* it fires `alarmo_failed_to_arm`. Home Modes followed that `disarmed` as if
   someone had disarmed at the keypad (mode went to Home) and the failure was never
   reported. The unit test fired the event first, so it did not catch this. Fixed, with a
   test in the real order.
2. **Refused guest actions were server errors.** They returned HTTP 500 and Home Assistant
   logged an ERROR line for every refused tap. Now HTTP 400 without the error log.

## Docs corrected

- With the default override *Next auto-rule trigger*, the next automatic trigger (for example
  everybody leaving) ends an override started at the Alarmo panel. Choose another override
  end if a keypad change must hold.
- The startup evaluation after a restart counts as that trigger: a manual Away while
  everybody is still home becomes Home after a restart.

## Notes from testing (no change needed)

- A test that restarts Home Assistant with a plain `docker restart` (10 s timeout) can kill it
  before it saves. With a normal stop or the restart action, a change made a second before
  the restart was kept.
- The `device_tracker.see` action is deprecated in 2026.11 (removed in 2027.5). Use template
  device trackers for test persons, as above.

## Not covered here (still open before 1.0)

- iOS and Android Companion apps: notification channels and interruption levels on a real
  phone, the cards in the apps, widgets.
- The cards in a real browser (layout, touch, themes) and README screenshots.
- HACS pre-release display and the Marketplace install.
- Ring keypad with the blueprint.
- Raspberry Pi load and Assist voice (to be done by the maintainer).
- A fresh install on 2026.10.4.
