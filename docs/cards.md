# Dashboard cards

Two Lovelace cards ship with the integration. They are plain JavaScript files in
`custom_components/home_modes/frontend/`: no build step, no CDN and no request to any other
host. Everything is served by your own Home Assistant.

| Card | Type | For |
| --- | --- | --- |
| Home Modes | `custom:home-modes-card` | The family dashboard: status, modes, overlays, Auto, optional temporary mode |
| Home Modes (guest) | `custom:home-modes-guest-card` | A restricted dashboard for guests, see [guest-dashboard.md](guest-dashboard.md) |

> Screenshots: _placeholder, to be added from a real installation (light and dark theme, phone
> and desktop). No mock-ups are shown here on purpose._

## How the cards are loaded

On startup the integration registers the folder `frontend/` as a static path
(`/home_modes_static/`) and adds `home-modes-cards.js?v=<integration version>` to the list of
extra modules that the Home Assistant frontend loads on **every** page. You do not have to add
a Lovelace resource.

| Where you use the card | What happens |
| --- | --- |
| Dashboard in **storage mode** (edited in the UI) | The card shows up in the card picker ("Home Modes", "Home Modes (guest)") and has a visual editor. |
| Dashboard in **YAML mode** (`mode: yaml`, with or without `resources:`) | The module is loaded the same way, because extra modules do not depend on the dashboard's resource list. Write `type: custom:home-modes-card` in your YAML. Dashboards written in YAML have no visual editor; the options below are the whole configuration. |
| The `frontend` integration is not set up | The files are still served but not loaded automatically. Add a resource by hand: URL `/home_modes_static/home-modes-cards.js`, type *JavaScript module*. |
| Frontend in safe mode | Home Assistant skips all extra modules; the cards do not load. |

**Updates.** The URL contains the integration version, so a new version is fetched instead of
the cached file. After the **first install** (and after an update) reload the browser page, or
fully close and reopen the Companion app, once.

## `custom:home-modes-card`

All options are optional; with no configuration the card shows the status, every mode and
overlay you may set, and the Auto button.

```yaml
type: custom:home-modes-card
title: House mode            # optional
layout: full                 # full (default) or compact
show_status: true            # current mode, "since", Auto on/off, override, temporary
show_overlays: true          # Guest, Do not disturb (overlays you may set)
show_auto: true              # the "Auto" button (calls home_modes.set_auto)
show_temporary: false        # "For: 30 min / 1 h / 2 h / 4 h" in front of the mode buttons
roles: [home, night, away]   # only these role ids (a subset of what you may set)
icons:                       # per role id, any mdi: icon
  night: mdi:bed
entity: select.home_mode     # only needed if you renamed the select entity
```

- **Status.** Shows the current mode (name and icon), how long ago it was set, whether
  auto-rules are on, the **manual override** (until what time, or "until the next automatic
  change" / "until you press Auto") and an active **temporary mode** ("back to Home at 22:30").
- **Buttons.** One button per enabled primary mode, one toggle per overlay. The active ones are
  highlighted (`aria-pressed`). Buttons are at least 44 px high and wide. Nothing depends on
  hover.
- **Auto** calls `home_modes.set_auto` (ends a manual override and re-evaluates the auto-rules).
  It is hidden for users who may not use it (guests).
- **Temporary.** With `show_temporary: true` a "For" menu appears. Pick a duration, then a mode
  button calls `home_modes.set_temporary` instead of `set_mode`.
- **Names and ids.** The card uses role **ids** for every call and role **names** only as
  labels, so it works with renamed and custom modes. Nothing about Home, Night, ... is
  hard-coded.
- **Icons.** Default icons are chosen per role type. `icons:` overrides them per role id. Only
  values that look like `mdi:name` are accepted; anything else falls back to the default.
- **Themes.** Colours come from Home Assistant CSS variables (`--primary-color`,
  `--card-background-color`, `--divider-color`, `--error-color`, ...), so themes and dark mode
  apply. The card uses `ha-card` and `ha-icon`.

### Messages

| Situation | What the card shows |
| --- | --- |
| The integration is not loaded | "Home Modes is not loaded. Check Settings > Devices & services." |
| An action is refused (for example a guest tries a mode that is not on their list) | The server's message, for example "You are not allowed to change Night.", under the buttons for 8 seconds |
| No modes or overlays are available to you | "No modes are available for you." |
| The select entity cannot be found | "The Home Modes entity was not found." |

## Visual editor

Both cards have a visual editor (`getConfigElement` / `getStubConfig`), built on the
`ha-form` element that Home Assistant already provides, so it needs no build tooling. It offers
title, layout, the show/hide switches, the role subset and one icon picker per role. The role
lists come from the same server command as the card.

## Security and privacy

- All text that comes from the server (role names, the title) is written with `textContent`;
  no `innerHTML` is used. A role called `<img src=x onerror=...>` is shown as text.
- The card never contacts any other host and does not store anything in the browser.
- **A card is not a security boundary.** Hiding a button only saves a refused click. Permissions
  are enforced on the server for every service and entity, whatever a card shows. See
  [guest-dashboard.md](guest-dashboard.md).

## Known limits

- Without a browser the cards could only be tested in a simulated DOM. See
  [manual-test-checklist.md](manual-test-checklist.md) for the checks to do on desktop, iOS and
  Android.
- The cards re-read the list of allowed modes when the select's options change, when the page
  becomes visible again, and on first load. If an administrator changes permissions while a
  page is open, the page shows the new list after the next such moment (or a reload).
- Text is English only.
