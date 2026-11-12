"""Diagnostics: useful, and nothing that identifies a person is in them."""

from __future__ import annotations

import json
from contextlib import suppress

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.home_modes.diagnostics import REDACTED, async_get_config_entry_diagnostics

from .helpers import advance, call, presence_options, roles_without, setup_entry

SECRETS = [
    "Anna",  # person
    "anna_phone",
    "Annas study",  # custom role name
    "light.annas_room",
    "alarm_control_panel.alarmo_secret",
    "input_select.annas_house",
    "binary_sensor.annas_bed",
    "Anna is home",  # message
    "Welcome back, Anna",  # title
    "notify.mobile_app_anna_phone",
    "my_secret_notify_service",
    "light.hidden_hall",
]


async def test_diagnostics_are_useful_and_redacted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user, hass_admin_user
) -> None:
    """The report has state, settings, timers, history and versions, but no personal data."""
    roles = roles_without()
    roles.append({"id": "custom_1", "name": "Annas study", "enabled": True})
    options = {
        "roles": roles,
        **presence_options(["person.anna"], away=4),
        "night": {"methods": ["sleep_sensor"], "sleep_sensors": ["binary_sensor.annas_bed"]},
        "user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}},
        "alarmo": {
            "enabled": True,
            "entity_id": "alarm_control_panel.alarmo_secret",
            "mappings": [{"state": "armed_night", "role": "night", "to_alarmo": True}],
        },
        "vacation_sim": {"enabled": True, "lights": ["light.annas_room", "light.hidden_hall"]},
        "notify": {
            "rules": [
                {
                    "event": "any_change",
                    "targets": ["notify.mobile_app_anna_phone"],
                    "services": ["my_secret_notify_service"],
                    "message": "Anna is home",
                    "title": "Welcome back, Anna",
                }
            ]
        },
        "mirror": {
            "enabled": True,
            "entity_id": "input_select.annas_house",
            "mapping": {"home": "Home"},
        },
        "actions": {},
    }
    entry = await setup_entry(hass, freezer, options)
    await call(hass, "set_mode", {"mode": "night"}, user_id=hass_admin_user.id)
    with suppress(HomeAssistantError):
        await call(hass, "set_mode", {"mode": "away"}, user_id=guest_user.id)
    await call(hass, "set_temporary", {"mode": "custom_1", "duration": "00:30:00"})
    await advance(hass, freezer, minutes=1)

    diag = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diag, default=str)

    for secret in SECRETS:
        assert secret not in dumped, secret
    assert guest_user.id not in dumped
    assert hass_admin_user.id not in dumped

    # Useful content is there.
    assert diag["versions"]["integration"] == "0.9.1"
    assert diag["versions"]["home_assistant"]
    assert diag["state"]["primary"] == "custom_1"
    assert diag["state"]["temporary"]["revert_to"] == "night"
    assert diag["state"]["auto_enabled"] is True
    assert diag["timers"]  # the temporary expiry timer
    roles_by_id = {r["id"]: r for r in diag["roles"]}
    assert roles_by_id["custom_1"]["name"] == REDACTED
    assert roles_by_id["home"]["name"] == "Home"
    assert diag["settings"]["persons_configured"] == 1
    assert diag["settings"]["user_rules"] == {"count": 1, "allow_list": 1}
    assert diag["settings"]["alarmo"]["entity_configured"] is True
    assert diag["settings"]["vacation"]["lights_configured"] == 2
    assert diag["settings"]["notify"]["rules"] == [
        {"event": "any_change", "role": None, "target_count": 2, "has_message": True}
    ]
    assert diag["settings"]["mirror"] == {
        "enabled": True,
        "entity_configured": True,
        "mapped_roles": ["home"],
    }
    kinds = [e["kind"] for e in diag["history"]]
    assert "primary" in kinds and "denied" in kinds
    denied = next(e for e in diag["history"] if e["kind"] == "denied")
    assert denied["had_user"] is True and "user_id" not in denied and "user" not in denied


async def test_diagnostics_history_is_limited_and_drops_bridge_targets(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Only the newest entries are included, and bridge notes keep reasons only."""
    entry = await setup_entry(hass, freezer)
    history = entry.runtime_data.history
    for n in range(80):
        history.async_add_system(
            "notification_suppressed",
            {"reason": "rate_limited", "target": f"notify.secret_{n}", "event": "any_change"},
        )
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert len(diag["history"]) == 50
    assert "notify.secret_" not in json.dumps(diag)
    assert diag["history"][-1]["bridge"] == [{"reason": "rate_limited", "event": "any_change"}]


async def test_redaction_safety_net(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The final report passes through async_redact_data for the identifying key names."""
    from custom_components.home_modes import diagnostics

    for key in ("user_id", "targets", "message", "title", "entity_id", "lights", "persons"):
        assert key in diagnostics.TO_REDACT
