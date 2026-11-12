# Publishing guide (for a first-time GitHub publisher)

Goal: publish this project as the public repository **Home-Modes-Advanced** and release
**v0.9.0** as a pre-release. Parts marked **UNVERIFIED** could not be checked in the
development environment (no GitHub account was available); follow them and tell me what differs.

## 1. Create the repository

1. Sign in on github.com → **+** (top right) → **New repository**.
2. Owner: your account `Ryckie` (the links in the project use this name). Name: `Home-Modes-Advanced`.
3. Public. **Do not** tick "Add a README", ".gitignore" or "license" (the project already has them).
4. Create repository. Leave the page open; it shows the repository URL.

## 2. Push the files

Unzip `Home-Modes-Advanced-v0.9.0.zip` (it contains the folder `Home-Modes-Advanced`). In a terminal:

```bash
cd Home-Modes-Advanced
git init -b main
git add .
git commit -m "Home Modes Advanced 0.9.0"
git remote add origin https://github.com/Ryckie/Home-Modes-Advanced.git
git push -u origin main
```

GitHub asks you to sign in (use a personal access token or the GitHub CLI `gh auth login`;
passwords are not accepted for git). Check on github.com that the files are there and that
`.github/workflows/` is present.

## 3. Repository settings

Settings → General:

- **Description** (the HACS check requires one): `Home Modes Advanced: a local house-mode integration for Home Assistant (community project)`.
- **Topics** (click the gear next to "About" on the main page): `home-assistant`, `hacs`, `home-assistant-custom-component`, `integration`, `home-modes`.
- **Features**: make sure **Issues** is ticked (HACS checks this).
- **Default branch**: `main` (Settings → Branches; it is `main` already if you used the commands above).

Settings → Security (or "Code security"):

- **Private vulnerability reporting**: Enable. `SECURITY.md` relies on it.

Settings → Actions → General:

- "Allow all actions and reusable workflows" is fine; workflow permissions can stay at the default
  because every workflow declares its own permissions. For the release workflow to create a
  release, the repository must allow it (see section 6, troubleshooting).

## 4. Read the Actions results

1. Open the **Actions** tab. The push started the workflows **Validate** (hassfest and HACS) and **Tests**.
2. Green check = passed; red cross = failed; yellow = running. Click a run → click a job → click
   a step to read its log. Tests for Home Assistant 2026.11.1 are "best effort": that job may be
   red without blocking anything (it is allowed to fail).
3. **None of these workflows has ever run** (UNVERIFIED), so expect that the first run may need a fix.

### If hassfest fails

- Open the failed step and read the lines that start with the file name and a reason.
- Common causes: a manifest key in the wrong order or missing, a translation string used in the
  code but missing from `translations/en.json`, or a service in `services.yaml` without a description in `en.json`.
- Fix the file, commit and push; the workflow runs again. If the message is unclear, copy the
  failed step's log into a GitHub issue or the community thread.
- The step uses `home-assistant/actions/hassfest@master`, which is floating by Home Assistant's
  own documentation, so a new rule can appear without a change in this repository.

### If the HACS action fails

- The HACS checks are: archived, brands, description, hacsjson, images, information, issues,
  license, topics. The most common failures are a missing **description**, missing **topics**,
  **Issues** turned off, or a missing brand `icon.png`: fix them in the settings (section 3).
- Then open the run → **Re-run failed jobs**.
- The "brands" check may complain about the placeholder images or about brand registration.
  If it blocks you, tell me the exact message (UNVERIFIED how this check treats local `brand/` folders).
- The step uses `hacs/action@main` (floating by design; its newest tag is old).

### If the Tests or Ruff/mypy jobs fail

Run the same commands locally (see `CONTRIBUTING.md`) and read the first error.

## 5. Create the v0.9.0 pre-release

Before tagging: the manifest version is `0.9.0`, `CHANGELOG.md` has `## [0.9.0]`, and the Validate and Tests runs on `main` are green.

### Option A: automatic, with `release.yml`

```bash
git tag v0.9.0
git push origin v0.9.0
```

The **Release** workflow runs hassfest, HACS validation and the tests, checks the tag against the
manifest (`.github/scripts/release_info.py`), then creates the GitHub release with the changelog
text. Because the version is below 1.0.0 it is marked **Pre-release**. Check: repository main page →
**Releases** on the right → v0.9.0 shows a "Pre-release" badge.

If the release step fails with a permissions error: Settings → Actions → General → Workflow
permissions → "Read and write permissions", then re-run the failed job (UNVERIFIED whether this is needed;
the workflow requests `contents: write` itself).

### Option B: manually

1. Create the tag as above (or let GitHub create it in the next step).
2. Repository → **Releases** → **Draft a new release**.
3. Choose tag `v0.9.0` (target `main`), title `v0.9.0`.
4. Paste the `## [0.9.0]` section of `CHANGELOG.md` as the description.
5. Tick **Set as a pre-release**. Publish release.

Do not tick "Set as the latest release" for a beta if you can avoid it (UNVERIFIED how this
interacts with HACS version selection).

## 6. Install it as a custom repository

**HACS (Home Assistant 2026.10.x and older than 2026.11):**
HACS → ⋮ → Custom repositories → repository `https://github.com/Ryckie/Home-Modes-Advanced`,
category **Integration** → Add. Open it → enable **Show beta versions** if v0.9.0 is not offered →
Download. Restart Home Assistant. (Whether HACS lists a pre-release without "Show beta
versions" is UNVERIFIED; the README says to enable it.)

**Marketplace (Home Assistant 2026.11 and newer):**
Settings → Marketplace → add the repository the same way. The Marketplace uses the same catalog
format and `hacs.json`. The exact screens and how pre-releases are shown were **not verified**
(UNVERIFIED). If you cannot find "add custom repository", look in the Marketplace menu and tell me what it is called.

Then follow [smoke-test.md](smoke-test.md).

## 7. Uninstall

1. Settings → Devices & services → Home Modes Advanced → ⋮ → **Delete**. This removes the entities,
   the device and the integration's stored files (state, history, vacation data). Vacation
   lighting that the integration switched on is switched off. History already written to the
   recorder stays until the recorder purges it.
2. HACS / Marketplace → Home Modes Advanced → ⋮ → **Remove** (or Redownload/Delete). This removes
   `custom_components/home_modes`. Restart Home Assistant.
3. Delete automations you created from the blueprints, and remove the card from your dashboards.
4. Blueprints imported by you stay in `/config/blueprints/automation/home_modes/` until you delete them.

## 8. What I could not verify

- Everything on GitHub: the workflows, the repository settings pages and their current names, release creation, tokens.
- HACS: custom repository screens, pre-release visibility, "Show beta versions" wording.
- The Marketplace screens and pre-release display on Home Assistant 2026.11.
- How the HACS "brands" check treats the placeholder images.
