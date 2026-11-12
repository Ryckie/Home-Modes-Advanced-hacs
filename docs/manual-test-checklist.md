# Manual test checklist (Steps 3, 4 and 5)

Use a test Home Assistant (2026.10.4 or newer). Create one admin user and one non-admin user
("guest"). Add two `person` entities (or helpers that mimic them) and, for the sensor tests,
input booleans exposed as binary sensors (template) or any real sensors.

## Install and setup

- [ ] Add the integration with the **Simple** preset: select options are Home, Night, Away,
      Vacation; no `binary_sensor.home_mode_all_home` / `all_away`.
- [ ] Remove it and add it with **Extended**: Home, Night, Away, Vacation, All home, All away
      are selectable; Guest and Do not disturb have overlay switches; `all_home` / `all_away`
      binary sensors exist.
- [ ] Only one entry can be created.

## Roles and names

- [ ] Rename Night to "Sleep": the select state becomes "Sleep"; the `role`/`mode_id`
      attributes still say `night`; `binary_sensor.home_mode_night` keeps its entity id.
- [ ] Renaming a mode to an existing name (any letter case) is rejected.
- [ ] Disabling the last enabled primary mode is rejected.
- [ ] Disable the active mode in the options: the mode switches to the previous enabled
      primary-kind mode, else the first enabled one (never All home / All away); trigger reason
      shows `system` with rule `role_disabled`.
- [ ] Add a custom mode: `binary_sensor.home_mode_custom_1`, select attribute `role: custom`,
      `mode_id: custom_1`.

## Presence (options → Presence and away timers: both persons, away delay 1 min for the test)

- [ ] Both persons home, mode Home. Set one to away: nothing happens.
- [ ] Set the second to away: after the delay the mode becomes All away (Extended) or Away
      (Simple). Trigger reason `presence`, rule `presence_away` / `presence_all_away`.
- [ ] Repeat, but set a person home before the delay ends: no change.
- [ ] Set a person to `unavailable` or `unknown` while everybody is home: no change, even after
      the delay time.
- [ ] While away, set one person home: mode becomes Home (rule `presence_arrival`).
- [ ] Extended: both home from Home -> mode becomes All home; one leaves -> back to Home.
- [ ] Vacation: set vacation_after to 1 h (or use a template to shorten) and keep everybody
      away: mode becomes Vacation. With Vacation disabled it stays Away.

## Night and morning

- [ ] Night -> Time window starting 2 minutes from now: mode becomes Night (source `schedule`).
- [ ] Night -> Sleep sensor: turn the sensor on: Night (source `sensor`).
- [ ] Night -> Phone charging: charging on **outside** the window: nothing; inside: Night.
- [ ] Night rules never fire while the mode is Away or Vacation.
- [ ] Morning -> Time: at that time Night becomes Home (source `schedule`).
- [ ] Morning -> Motion: motion before the "earliest" time or after the night window start does
      nothing; in between it ends Night.
- [ ] Morning -> Alarm: set a next-alarm timestamp sensor 2 minutes ahead: Night ends then.
- [ ] A rule whose target mode is disabled does nothing.

## Overrides

- [ ] As a user, change the mode in the UI (default `next_auto`): the mode sticks until the next
      auto-rule trigger would fire, then that rule applies and the override is gone.
- [ ] Set override to `duration` (2 min): auto-rules are ignored for 2 minutes, then applied.
- [ ] Set override to `end_of_day`: ignored until midnight.
- [ ] Set override to `set_auto`: ignored indefinitely; Developer tools -> `home_modes.set_auto`
      clears it and re-evaluates now.
- [ ] Call `home_modes.set_mode` from Developer tools (this is a user call): override starts.
      From an automation or script without a user: no override, unless `override: true`.
- [ ] `override: false` as a user: no override.

## Temporary, revert, auto switch

- [ ] `set_temporary` mode Away, 2 minutes: Away now; after 2 minutes back to the previous
      mode, trigger reason `temporary_expiry`.
- [ ] During a temporary mode pick another mode: no revert happens later.
- [ ] `revert` goes back to the previous mode; calling it again goes forward again.
- [ ] `switch.home_mode_auto` off: no auto changes (presence, night, morning). On: auto-rules
      are evaluated immediately.

## Restart

- [ ] Start an override (duration 30 min), restart Home Assistant: the override is still active
      afterwards and ends on time.
- [ ] Start `set_temporary` (5 min), stop Home Assistant for more than 5 minutes, start it: the
      mode reverts once at startup.
- [ ] Everybody away (mode Away), stop Home Assistant for longer than vacation_after, start it:
      the mode becomes Vacation at startup.

## Permissions (options → User permissions)

- [ ] Set the guest user to Allow-list with only Home and Away. As the guest (UI or a script
      run by the guest): Away/Home work; Night is denied with "not allowed" and
      `home_modes_denied` fires (Developer tools -> Events).
- [ ] As the guest: `set_temporary` to Night, `revert` while the previous mode is not allowed,
      and `set_auto` are denied; `switch.home_mode_auto` cannot be toggled.
- [ ] Admin is never restricted. A user without a rule is unrestricted.
- [ ] Known limitation: an automation triggered by the guest runs unrestricted.

## Events and entities

- [ ] `home_modes_changed` payload contains kind, from, to, role, active, overlays, source,
      rule, user_id for both a primary change and an overlay toggle.
- [ ] `sensor.home_mode_trigger_reason` shows the source and its `rule` attribute for every
      auto change.

## Actions (options → Integrations → Enter and exit actions)

- [ ] Give *Night* an enter action (turn a test light on) and *Home* an exit action (fire an event
      or send a notification). Switch Home → Night: the exit action runs first, the light comes
      on after the select changed.
- [ ] Add an action that fails (unknown service) and one after it: the second still runs, the
      mode changes, the history entry shows the failure.
- [ ] Add a `delay` longer than the timeout: the change finishes, the history shows a timeout.
- [ ] Enter action of *Away* = `home_modes.set_mode` to *Home*, and the reverse: after a few
      changes the loop is stopped with a warning and an `action_loop_blocked` history entry.
- [ ] Guest overlay and a custom mode also run their actions.

## History

- [ ] Change modes; open the logbook: entries read "changed from X to Y (source: …)".
- [ ] Restart Home Assistant: the entries are still there. Set the size to 10 and make 12 changes:
      only the newest 10 remain.
- [ ] `home_modes.clear_history` as a non-admin user is refused; as admin it empties the log.
- [ ] Developer tools → websocket (or the browser console) `home_modes/history`: admin sees all,
      a normal user sees changes only, an allow-list guest gets an empty list.

## Notifications

- [ ] With no rule: nothing is sent. Add a rule *any change → your mobile_app service*: you get
      one notification per change; two identical changes within 10 s send one.
- [ ] Android: the channels `HM_ModeChanges`, `HM_Alerts`, `HM_Guests` appear in the app's
      notification settings. iOS: mode changes are silent (passive), a denied attempt is
      time-sensitive.
- [ ] Template `{{ user }} → {{ to_mode }} at {{ time }}` renders; an invalid template is rejected
      in the options.
- [ ] Break the target (typo in the service name): the mode change still works and a warning is
      logged.

## Vacation simulation (use two or three test lights)

- [ ] Enable it, pick the lights, window around the current time, short on-durations. Set mode
      Vacation: the lights switch on/off inside the window only; other lights are untouched.
- [ ] Switch to Home while a light is on: it goes off; the history has one start and one stop
      entry; no notification.
- [ ] Restart Home Assistant during the window: the simulation continues; lights it turned on
      are switched off at their planned time.
- [ ] Strategy *replay* with the recorder: copies last week's same weekday. Disable the recorder
      (or use a light with no history): a warning is logged and random is used.

## Alarmo bridge

Run the whole section twice: **A. without Alarmo installed**, **B. with Alarmo**.

A. Without Alarmo
- [ ] Enable the bridge, save: no error, Home Assistant starts normally. Change a mode: it works;
      the history entry has the note `alarmo_not_found`; a `bridge_error` rule (if any) notifies
      once.

B. With Alarmo (default arm/disarm without codes for the test; note the exit delay of each mode)
- [ ] Mapping: Away ↔ armed_away, Night ↔ armed_night, Home ↔ armed_home, `disarmed` → Home
      (Alarmo → Home Modes only, *Allow disarming* off).
- [ ] Set mode Away in Home Modes: Alarmo goes to *arming*, then *armed_away* after the exit
      delay; Home Modes stays on Away and does not change again (no echo).
- [ ] Set Alarmo to armed_night from the Alarmo panel: mode becomes Night, source `alarmo`,
      override active (`sensor.home_mode_trigger_reason`); a presence change does not undo it.
- [ ] Disarm from the Alarmo panel: mode becomes Home.
- [ ] Safety: map a mode to `disarmed` with *Allow disarming* **off**: switching to it never
      disarms. Turn it on: it disarms (as admin); as an allow-list guest it still does not.
- [ ] Safety: with *Apply automatic mode changes* off, let presence/schedule change the mode:
      Alarmo is not touched. Turn it on: arming follows, disarming still needs the switch.
- [ ] Trigger the alarm (or set it to *pending*/*triggered* in a test instance): mode changes do
      not interfere.
- [ ] Open a window sensor, set mode Away: Alarmo refuses; the mode stays Away; a bridge error is
      recorded.
- [ ] Turn on *require code to arm* in Alarmo: the history shows `code_required`, nothing is sent.
- [ ] Remove or disable Alarmo while the bridge is on: Home Modes keeps working, one bridge error.
- [ ] With the Ring Keypad blueprint: arm Away and disarm at the keypad. Home Modes follows
      (Away, then the disarmed mapping); the keypad shows the Alarmo state as before; the
      blueprint is unchanged. Leave the blueprint's own presence arming off.
- [ ] Direction `from_alarmo` only: Home Modes never calls Alarmo. Direction `to_alarmo` only:
      Alarmo changes do not change the mode.

## Cards (Step 5): repeat each block on desktop browser, iOS Companion app and Android Companion app

The automated checks run in a simulated DOM only (no layout, no real touch, no Home Assistant
elements). Everything below needs a real browser. Reload the page (or restart the Companion
app) once after installing.

Loading
- [ ] Add a card in the UI: "Home Modes" and "Home Modes (guest)" are in the card picker with
      their descriptions. No Lovelace resource was added by hand.
- [ ] Open the visual editor of each card: the form appears (title, layout, switches, role
      list, one icon picker per role). Changing a value updates the card preview; saving keeps
      it. The YAML editor shows the same options.
- [ ] Dashboard in **YAML mode** with `type: custom:home-modes-card`: the card renders.
- [ ] Browser developer tools (desktop): the network tab shows
      `/home_modes_static/home-modes-cards.js?v=<version>` and no other new host.

Full card
- [ ] Zero config: status block, a button per enabled mode, overlay buttons, an Auto button.
- [ ] The highlighted button matches `select.home_mode`; change the mode elsewhere: the card
      follows within a second.
- [ ] Tap each mode: the mode changes. Tap an overlay: it toggles. Tap Auto after a manual
      change: the override note disappears and the auto-rules take over.
- [ ] After a manual change the override line shows the expected end ("until HH:MM" or "until
      the next automatic change").
- [ ] `show_temporary: true`: pick 30 min, tap Night: the "back to ... at ..." line appears and
      the mode reverts on time.
- [ ] Rename a mode and add a custom mode in the options: the card shows the new names without
      any card change (use `roles:` only if you want fewer buttons).
- [ ] Dark theme and a custom theme: text and highlight colours stay readable.
- [ ] `layout: compact` fits on one or two rows on a phone; `layout: full` at 360 px width has
      no horizontal scrolling.
- [ ] Touch: every button is easy to hit with a thumb (at least 44 px), nothing needs hover or
      long press, no double-tap zoom on the buttons.
- [ ] Give a mode a name with `<b>` or `&` in it: shown literally, nothing is formatted.
- [ ] Disable the integration (Settings → Devices & services → disable): the card shows the
      "not loaded" message instead of an empty box.

Guest card (sign in as the non-admin user)
- [ ] Allow-list only Home and Guest: the card shows exactly those two, no Auto, no status.
- [ ] Tap Home and Guest: both work.
- [ ] Bypass the card: as the guest, call the service with a long-lived access token of the
      guest (`POST /api/services/home_modes/set_mode` with `{"mode": "night"}`): it is refused
      and the history shows a `denied` entry. The same for `home_modes.set_overlay` on an
      overlay that is not on the list.
- [ ] `roles: [night]` in the card config: the card shows nothing (it cannot add a role the
      server did not allow).
- [ ] Remove a mode from the allow-list while the guest's page is open, then switch away and back
      to the app: the button is gone.
- [ ] A refused action shows the server message under the buttons.

Companion app specifics
- [ ] iOS: the card appears in the app's dashboard, taps work, pull-to-refresh keeps it.
- [ ] Android: same; the app's WebView shows the card after "Reload resources" or a restart.
- [ ] A script per mode (see [companion-apps.md](companion-apps.md)) in a widget / Device
      Control: runs, and the mode changes.

## Assist

- [ ] Copy the sentence file ([assist.md](assist.md)), restart, say or type "set the house mode
      to night": the mode changes and Assist answers "House mode set to Night.".
- [ ] "turn on the guest mode" / "turn off the guest mode" toggle the overlay.
- [ ] A name that does not exist: "I don't know a mode called ...".
- [ ] Signed in as the guest in the app's Assist: a mode outside the allow-list is refused and
      appears in the history as denied.

## Migration from an input_select

- [ ] With a test `input_select`, run Options → Integrations → Import from input_select: every
      option has a suggestion; the preview matches; declining (or closing the dialog) changes
      nothing.
- [ ] Confirm with the mirror off: roles are renamed/enabled, custom modes added, the old
      input_select and your automations are untouched.
- [ ] Run `home_modes.import_input_select` without `confirm`: the response lists your
      automations, scripts and UI template helpers that use the input_select.
- [ ] Mirror on: changing the mode writes the option; renaming an option in the input_select
      makes the next change record `mirror_failed` in the history.
- [ ] Turn the mirror off again.
- [ ] Mirror overlays off (default): turning Guest on does not write anything. Turn the
      option on: Guest writes its option while it is active and the primary's option again
      when it ends.
- [ ] Confirm the import while another options edit is pending: only the import is saved
      and the dialog closes (the other edit is discarded, as the description says).

## Diagnostics

- [ ] Download diagnostics: no user names, notification targets, message texts, Alarmo or light
      entity ids, person entities or custom mode names are in the file.

## Release extras (Step 6)

- [ ] Import each of the three blueprints with the my.home-assistant.io button, create an
      automation from it, rename the mode it uses and confirm it still works.
- [ ] Change the time zone in Settings while a night timer is armed; the History/sensors show
      the next change at the new local time.
- [ ] Remove the integration: entities and device disappear, vacation lights are turned off,
      the input_select mirror stops, and adding the integration again starts clean.
- [ ] Debug logging on for a whole day: grep the log for your phone's notify service name and
      for message text; nothing should match.
