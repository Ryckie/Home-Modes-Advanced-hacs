# Release checklist

## Recommended first release

Tag **v0.9.1** and publish it as a **pre-release** (beta). Move to **1.0.0** only after the
"must test before 1.0" items below have been done on real hardware and the feedback from the
community thread has been handled.

## How a release works

1. Update `custom_components/home_modes/manifest.json` `version` and add a `## [X.Y.Z]` section
   (with the date) to `CHANGELOG.md`.
2. Merge to `main`; wait for `validate.yml` and `tests.yml` to be green.
3. Create and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. `release.yml` runs hassfest, HACS validation and the tests, then
   `.github/scripts/release_info.py` checks that the tag equals the manifest version, that
   `hacs.json` has a name and that the changelog has the section. It then creates the GitHub
   release with the changelog text. Versions below 1.0.0 or with a suffix (`-beta.1`) become
   **pre-releases**.
5. HACS uses the latest release's tag name as the version ("just publishing tags is not enough,
   you need to publish releases"). The Marketplace uses the same catalog format.

Tag format: `vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCH-suffix`. Run
`python .github/scripts/release_info.py vX.Y.Z` locally to check before tagging.

## Before the first public release (repository settings)

- [ ] Repository is public, has a description and topics (`home-assistant`, `hacs`,
      `home-assistant-custom-component`, `integration`) and Issues enabled (HACS checks this).
- [ ] **Security → Private vulnerability reporting** enabled (SECURITY.md relies on it).
- [ ] **v0.9.1 ships with the brand placeholders** (grey boxes marked "PLACEHOLDER"); replace them
      in `custom_components/home_modes/brand/` before 1.0 (see below).
- [ ] Add real screenshots under `docs/images/` and remove the placeholder note in the README.
- [ ] Run the GitHub workflows once on `main` and fix whatever they report (they could not be
      run in the development environment).
- [ ] Actions pins: the workflows pin `actions/*` to a major version. `hassfest@master` and
      `hacs/action@main` are floating by the maintainers' own documentation; check them when CI turns red.

### Brand images you must provide

Folder: `custom_components/home_modes/brand/` (Home Assistant 2026.3 and newer read local
images from here; they take priority over the brands CDN; do not use Home Assistant branded images).

| File | Size | Notes |
|---|---|---|
| `icon.png` | 256 × 256 | square, transparent background preferred |
| `icon@2x.png` | 512 × 512 | |
| `logo.png` | shortest side 128 to 256 | the wide logo |
| `logo@2x.png` | shortest side 256 to 512 | |
| `dark_icon.png`, `dark_logo.png` (+ `@2x`) | same as above | optional, for dark themes |

HACS requires at least `icon.png`.

## Must test before 1.0 (real devices)

Do these on a real instance and note the result in the release PR. Results of the
run on 2026.11.1: [real-instance-test-2026-11.md](real-instance-test-2026-11.md)
(the ticked items; the Ring keypad part of the Alarmo test is still open).

- [ ] **HACS pre-release display:** add the repository as a custom repository and check which
      version HACS offers for the v0.9.1 pre-release (UNVERIFIED how pre-releases are shown).
- [ ] **Marketplace on 2026.11:** install through Settings → Marketplace (UNVERIFIED).
- [ ] **Fresh install** on 2026.10.4 and on 2026.11.x: add the integration, both presets.
- [x] **Real Alarmo** with the steps in [real-alarmo-test.md](real-alarmo-test.md): arm and
      disarm from the Alarmo panel and from a keypad; confirm no echo loop and that Home Modes
      never disarms without "allow disarm".
- [ ] **iOS Companion app:** notification arrives with the right interruption level; the
      full card and the guest card render and buttons work; a Shortcut that calls
      `home_modes.set_mode` works; the card looks right in light and dark theme.
- [ ] **Android Companion app:** channels `HM_ModeChanges`, `HM_Alerts`, `HM_Guests` appear and
      are configurable; the cards render; a widget or tile that starts a script works
      (UNVERIFIED which widget types can run scripts).
- [x] **Guest account:** a real non-admin user on a guest-only dashboard can only use allowed
      modes; denied attempts show in the history; check what the user can see in the sidebar.
- [x] **Migration:** import a real `input_select`, check the preview, the mirror and the usage report.
- [x] **Restart during an override** and **restart during a temporary mode** on the real instance.
- [x] **A real DST change or a manual time zone change** while a night timer is armed
      (or at least change the time zone in Settings and watch the timers).
- [ ] **Raspberry Pi (or similar):** note memory and CPU while the integration is idle and during
      a vacation simulation with replay.
- [ ] **Assist:** a custom sentence file from `docs/examples/` with your voice assistant, and
      which clients pass a user id (UNVERIFIED).
- [ ] The **visual editors** of both cards in the dashboard editor.
- [ ] The **my.home-assistant.io blueprint import buttons** (they point at `main`).
- [ ] The manual list in [manual-test-checklist.md](manual-test-checklist.md), with and without Alarmo.

## After the release

- [ ] Install from the published release on a clean instance.
- [ ] Post the text from [community-post-draft.md](community-post-draft.md) in the thread, after
      replacing the placeholders.
- [ ] Move the changelog's `[Unreleased]` section forward.
