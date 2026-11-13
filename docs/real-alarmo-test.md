# Test the Alarmo bridge on a real setup

For a user with a real Alarmo (and optionally the Ring Keypad V2 + blueprint). Use a quiet
moment, tell the household, and keep a way to disarm. Allow about 30 minutes. Mark what
happens; attach the log lines listed at the end when something does not match.

## 0. Prepare

1. Enable debug logging ([debug-logging.md](debug-logging.md)):
   `custom_components.home_modes.alarmo` and `custom_components.home_modes.engine`.
2. In Alarmo: for the test, use modes **without a code** and note the exit delay of each mode.
3. In Home Modes: Options → Integrations → Alarmo bridge: enable, direction *both*, pick the
   Alarmo entity, *Apply automatic mode changes* **off**.
4. Mapping: `armed_away` ↔ Away, `armed_night` ↔ Night, `armed_home` ↔ Home (both directions);
   `disarmed` → Home (Alarmo → Home Modes only, *Allow disarming* **off**).
5. Disarm Alarmo, set Home Modes to Home.

## 1. Alarmo → Home Modes

1. Arm Alarmo **Night** from the Alarmo panel. Expect: after the exit delay Home Modes switches
   to Night, `sensor.home_mode_trigger_reason` says source `alarmo`, rule `alarmo:armed_night`,
   and the history entry shows source `alarmo`. No call goes back to Alarmo.
2. Check the override: set *Manual override* to *Until set_auto* and let a presence or
   schedule rule trigger: Night stays. Call `home_modes.set_auto` to clear it. (With the
   default *Next auto-rule trigger*, that trigger ends the override and applies, by design.)
3. Disarm Alarmo. Expect: Home Modes switches to Home (`alarmo:disarmed`).
4. With the Ring keypad: press Arm Away and disarm with the code. Expect the same as above and
   that the keypad shows the Alarmo state exactly as without Home Modes.

## 2. Home Modes → Alarmo and the exit delay

1. Set mode **Away** in Home Modes. Expect: Alarmo goes *arming*, counts the exit delay, then
   *armed_away*. Home Modes stays on Away and does **not** change again afterwards.
2. Set Home in Home Modes while Alarmo is `armed_away`. Expect: Alarmo stays armed (the
   `disarmed` row is not "to Alarmo", and *Allow disarming* is off). The history entry shows
   `disarm_not_allowed` or no Alarmo note.
3. During an exit delay, disarm at the panel/keypad. Expect: Home Modes follows to Home and
   no new arm command is sent.

## 3. Safety defaults

1. **No automatic disarm.** Add a `to_alarmo` row `disarmed` → Home with *Allow disarming*
   **off**. Arm Away, then set Home. Alarmo must stay armed; the history says
   `disarm_not_allowed`.
2. **Explicit switch.** Turn *Allow disarming* **on** for that row, arm Away, set Home as admin:
   Alarmo disarms. Do it as an allow-list user: Alarmo must stay armed.
3. **No auto-rule arming.** With *Apply automatic mode changes* off, let presence or the night
   schedule change the mode: Alarmo must not change. Turn the option on: arming follows,
   disarming still needs the row switch. Turn the option off again when done.
4. **Busy alarm.** Trigger a *pending* (entry delay) state and change the mode: Alarmo must not be
   touched (`alarm_busy:...` in the history).
5. **No restart sync.** Restart Home Assistant in each mode: nothing is armed or disarmed.

## 4. Failed to arm and codes

1. Open a window/door sensor that Alarmo checks and set Away. Expect: Alarmo refuses; Home Modes
   stays on Away; a system history entry `bridge_error` / `failed_to_arm` appears (and a
   notification if you made a `bridge_error` rule).
2. Switch on *require code to arm* in Alarmo and set Away. Expect: nothing is sent and the history
   says `code_required`. Switch the requirement off again.

## 5. Alarmo missing

Disable the Alarmo integration (or its entity) and change a mode. Expect: the mode changes and
the history says `alarmo_not_found` or `alarmo_unavailable`; only one notification per outage.
Re-enable Alarmo; the bridge works again without a restart of Home Modes.

## Log lines to attach to a bug report

Set the two loggers above to `debug`, repeat the failing step once, and attach:

- all lines containing `home_modes` from Settings → System → Logs (or `home-assistant.log`)
  from 10 s before to 60 s after the step;
- the newest 20 history entries (Developer tools → Actions is not needed: download the
  diagnostics of the integration, which are redacted, see [debug-logging.md](debug-logging.md));
- the Alarmo state history of the alarm entity for the same minute (Logbook / History).

Remove anything you consider private before posting. The integration does not log codes,
message templates or full notification targets.
