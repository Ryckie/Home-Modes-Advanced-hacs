# Guest dashboard

Give a guest, a child or a house-sitter one small dashboard where they can set only the modes
you allow.

> **A card alone is not a security boundary.** The guest card only hides what the server would
> refuse anyway. The protection is the **allow-list** you set in the options: the services
> (`home_modes.set_mode`, `set_overlay`, `set_temporary`, `revert`, `set_auto`), the select
> entity and the overlay switches all check it on the server for the user who made the call, no
> matter which card, script or API client was used.

## 1. Create a non-admin user

1. Settings → People → **Add person**.
2. Turn on **Allow person to login**, choose a username and password.
3. **Leave "Administrator" off.** Administrators are never restricted.

(Optionally turn on "Can only log in from the local network".)

## 2. Set the allow-list

Settings → Devices & services → Home Modes Advanced → **Configure** → *User permissions*:

1. Pick the user.
2. Choose **Allow-list** and tick the modes and overlays they may set, for example Home and
   Guest.
3. Save.

Effects for an allow-list user: they can change only the listed roles, and they cannot use
`set_auto` or the Auto switch. A user without a rule, or with *Unrestricted*, can change every
role. Administrators are always unrestricted. Denied attempts are recorded in the
[history](history.md) (administrators see all of them; the user sees their own).

## 3. A dashboard the guest can see

Settings → Dashboards → **Add dashboard** (new dashboard, "Home Modes guest" for example).
Check the dashboard's **Require admin** setting: it must be **off** for the guest to see it.
_(Verified in the Home Assistant source: the dashboard field is `require_admin` and it defaults to off for new dashboards. The exact wording of the toggle in the UI was not checked.)_

Alternatively, put the card in a view that only this user sees:

```yaml
views:
  - title: House
    visible:
      - user: 0123456789abcdef0123456789abcdef   # the guest's user id (Settings → People → user)
    cards:
      - type: custom:home-modes-guest-card
```

Non-admin users cannot edit dashboards and do not see the Settings pages. Home Assistant has
no per-user entity visibility: a non-admin user who knows an entity id can still look at its
state through the API. That is why the real protection is the allow-list.

## 4. Add the card

```yaml
type: custom:home-modes-guest-card
title: House mode
```

The card asks the server which roles **the signed-in user** may set (the websocket command
`home_modes/allowed_roles`) and shows only those: no other user's rules are sent. Options:

```yaml
type: custom:home-modes-guest-card
title: House mode
layout: compact            # compact (default) or full
show_overlays: true
roles: [home, guest]       # optional: show fewer of the allowed roles
```

`roles` can only **narrow** the list. A role the server did not return is never shown, even if
you list it. The guest card never shows Auto or the temporary control.

## What a guest can and cannot do

| Can | Cannot |
| --- | --- |
| Set the modes and overlays on their allow-list, from the card, the select entity or an action | Set any other mode or overlay (denied, recorded in the history) |
| See the current mode on the card | Use `set_auto` or the Auto switch |
| Read their own denied attempts in the history | See other users' history entries, action failures or notification details |

## Security notes

Home Modes enforces the allow-list on the server, but Home Assistant itself has no
per-service or per-entity permissions for non-admin users. What that means in practice:

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

Voice assistants are in the same position: see [assist.md](assist.md).
