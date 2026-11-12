# Home Modes Advanced

A first-class "house mode" for Home Assistant: one primary mode (Home, Night, Away, Vacation,
custom modes), stackable overlays (Guest, Do not disturb), automatic rules driven by presence,
time and sensors, manual overrides, and server-side permissions for guests.

> **Community integration.** This is an independent, community-built custom integration. It is
> not made, endorsed or supported by Nabu Casa or the Home Assistant project.

> **Beta (0.9.0).** The icon and logo are **placeholders** and will be replaced before 1.0.
> Tested with automated tests only. Not yet tested with a real Alarmo, on real
> iOS and Android devices, or on a Raspberry Pi. See [Status](#status).

## Why

Many setups rebuild the same thing with an `input_select`, a pile of automations and a lot of
copy-paste. The idea of a built-in "home mode" is discussed in the community thread
[WTH: why is there no Home Modes?](https://community.home-assistant.io/t/wth-why-is-there-no-home-modes/1033966).
This integration is one attempt at the shape of that feature, built on public APIs only.

## Features

- **Roles, not names.** Every mode is a role with a stable id; `binary_sensor.home_mode_<role>`
  and the `mode_id` attribute keep working when you rename a mode.
- **Primary + overlays.** Exactly one primary mode at a time; Guest and Do not disturb stack on top.
- **Auto-rules with fixed priorities.** Presence (away delay, vacation after N hours), night and
  morning methods (time, sleep sensors, phone charging, motion, alarm). Manual changes win and
  can start an override. [Rules](docs/priority-and-overrides.md).
- **Server-side permissions.** Per-user allow-lists; a guest card that only offers what a guest may do.
- **Enter and exit actions** per mode, with timeout and loop protection.
- **Optional Alarmo bridge** (off by default). It never disarms automatically.
  [Details](docs/alarmo-and-ring-blueprint.md).
- **Vacation simulation** (random or replay of last week), **notifications** with Companion
  channels, **history log**, **Assist intents**, dashboard **cards**.
- **Migration helper** for an existing `input_select`, with an optional one-way mirror.
- **Example blueprints** and copy-paste examples.
- Fully local: no cloud, no external Python dependencies, no external requests from the cards.

## Install

- **Home Assistant 2026.11 and newer:** Settings → Marketplace, add this repository (the
  Marketplace uses the same catalog format and `hacs.json` as HACS). _Not yet verified on a real
  2026.11 instance._
- **Older versions (2026.10.4 and newer):** HACS → three-dot menu → Custom repositories →
  add `https://github.com/Ryckie/Home-Modes-Advanced`, category **Integration**.
- **Pre-releases:** this is a beta published as a GitHub pre-release.
  HACS: enable "Show beta versions" to see pre-releases.
  Marketplace: verify how pre-releases are shown (**UNVERIFIED**: not confirmed from the
  current documentation).
- Restart Home Assistant, then Settings → Devices & services → Add integration →
  **Home Modes Advanced**.

Blueprints are not installed by the Marketplace or HACS; import them with the buttons in
[docs/examples.md](docs/examples.md).

## Quick start

1. Add the integration and choose the **Simple** preset (Home, Night, Away, Vacation) or **Extended** (adds
   All home, All away, Guest and Do not disturb). Roles can be turned on later.
2. Options → **Presence and away timers**: pick the person entities and the away delay.
3. Options → **Night methods** and **Morning methods**: choose how Night starts and ends.
4. Add the **Home Modes** card to a dashboard (see [cards](docs/cards.md)), or call
   `home_modes.set_mode`.
5. Use `binary_sensor.home_mode_night` (and the other role sensors) as conditions or triggers in
   your automations, or import a blueprint.

Everything else is off until you turn it on: notifications, Alarmo bridge, vacation simulation,
the mirror and enter/exit actions.

## Screenshots

_Placeholders: screenshots will be added from a real installation, not mock-ups._

- `docs/images/card-full.png`: the Home Modes card (light and dark theme)
- `docs/images/card-guest.png`: the guest card on a phone
- `docs/images/import-preview.png`: the input_select import preview

## Blueprints

| Blueprint | Import |
|---|---|
| Lights off at night | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Flights_off_at_night.yaml) |
| Heating setback in away and vacation | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Fheating_setback_away_vacation.yaml) |
| Notify on vacation or guest | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRyckie%2FHome-Modes-Advanced%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhome_modes%2Fnotify_vacation_or_guest.yaml) |

## Notifications and privacy

The integration itself is local. Notifications sent to the Companion app are delivered through
Apple's and Google's push services; that is how the apps work, not something this integration
adds. Nothing else leaves your installation.

## Security notes

Home Modes enforces the allow-list on the server, but Home Assistant itself has no per-service
or per-entity permissions for non-admin users. What that means in practice:

- **A non-admin guest can call any service the API allows**, not only what the guest card
  shows. The card only hides buttons. Home Modes denies modes and overlays outside the guest's
  allow-list, but it cannot restrict other integrations' services.
- **Automations run without a user and are trusted.** A change that comes from an automation
  has no user id, so the allow-list does not apply to it.
- **A guest can trigger an automation that sets a mode** (for example with the
  `automation.trigger` action, or by pressing a button that an automation reacts to). The mode
  change then goes through as the automation's change, not as the guest's.
- A **script a guest starts** keeps the guest's identity for the actions inside it, so the
  allow-list still applies there (tested).

Recommendations:

1. Keep guests on a dashboard that contains only the guest card.
2. Avoid automations that set a mode and that a guest can trigger.
3. Do not give guests access to scripts or automations.
4. Review which entities guest users can see.
5. Treat guest accounts as lower-trust accounts, not as a security boundary.

Report vulnerabilities privately: [SECURITY.md](SECURITY.md).

## Status

**Beta.** What exists and what has been checked:

| Area | Status |
|---|---|
| Automated tests (pytest, both Home Assistant versions below, about 325 tests) | passing locally |
| Home Assistant 2026.10.4 | primary target, required in CI |
| Home Assistant 2026.11.x | best effort in CI |
| DST, time zone change and clock-jump behaviour | covered by tests |
| Load / unload / reload, upgrade and removal | covered by tests |
| Card logic (browserless checks) | covered; visual rendering **not** checked on real devices |
| Alarmo bridge | tested against a fake Alarmo that follows its documented interface; **not** tested with a real Alarmo |
| iOS and Android Companion apps (notification fields, widgets, shortcuts) | **not tested** |
| Marketplace install on 2026.11 and HACS pre-release display | **not tested** |
| Raspberry Pi performance | **not measured** |
| GitHub workflows | written, not yet run on GitHub |

Details and the full list of open items: [security-and-quality.md](docs/security-and-quality.md)
and [release-checklist.md](docs/release-checklist.md).

## Documentation

- [Dashboard cards](docs/cards.md)
- [Guest dashboard](docs/guest-dashboard.md)
- [Assist (voice and text)](docs/assist.md)
- [Migrating from an input_select](docs/migration.md)
- [Companion apps: widgets and shortcuts](docs/companion-apps.md)
- [Priority and override rules](docs/priority-and-overrides.md)
- [Configuration, services and events](docs/configuration.md)
- [Copy-paste examples and blueprints](docs/examples.md)
- [Why integration_type is service](docs/integration-type.md)
- [Alarmo bridge and the Ring Keypad blueprint](docs/alarmo-and-ring-blueprint.md)
- [Notifications](docs/notifications.md)
- [Vacation simulation](docs/vacation-simulation.md)
- [History log](docs/history.md)
- [Debug logging](docs/debug-logging.md)
- [Translations](docs/translations.md)
- [Security and quality review](docs/security-and-quality.md)
- [Testing with a real Alarmo](docs/real-alarmo-test.md)
- [Manual test checklist](docs/manual-test-checklist.md)
- [Release checklist](docs/release-checklist.md)
- [Smoke test (10 minutes)](docs/smoke-test.md)
- [Publishing guide](docs/publishing-guide.md)
- [Final audit against the brief](docs/final-audit.md)
- [Brand images](docs/brand-images.md)
- [Blueprints](docs/blueprints.md)
- [Research: the new trigger platform](docs/research-new-trigger-platform.md)
- [Community post draft](docs/community-post-draft.md)
- [Repository layout](docs/repo-layout.md)

## Support and contributing

- Questions and ideas: the [community thread](https://community.home-assistant.io/t/wth-why-is-there-no-home-modes/1033966).
- Bugs: open an issue and attach the **diagnostics download** and a **debug log**
  ([how](docs/debug-logging.md)).
- Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md).
- Changes: [CHANGELOG.md](CHANGELOG.md).

## Development

```
python -m pip install -r requirements_test.txt
pytest                                    # Home Assistant 2026.10.4 (primary target)
(cd tests/js && npm ci && npm test)       # browserless card checks (needs Node 22)
python tests/run_pytest_ha2611.py         # Home Assistant 2026.11.x (best effort)
```

Licence: MIT, see [LICENSE](LICENSE).
