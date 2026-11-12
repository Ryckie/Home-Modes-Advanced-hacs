"""Guest dashboard: allowed_roles websocket and server-side enforcement."""

from __future__ import annotations

import json

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.home_modes.const import DOMAIN
from custom_components.home_modes.permissions import (
    UserRule,
    UserRuleMode,
    async_check_auto_control,
    async_check_role,
    auto_control_allowed,
    role_allowed,
)

from .conftest import make_entry
from .helpers import call, primary, setup_entry
from .test_history import CLIENT_ID


async def _client(hass: HomeAssistant, hass_ws_client, user):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))


async def _allowed(client) -> dict:
    await client.send_json({"id": 1, "type": "home_modes/allowed_roles"})
    reply = await client.receive_json()
    assert reply["success"], reply
    return reply["result"]


def _ids(items: list[dict]) -> list[str]:
    return [i["id"] for i in items]


async def test_allowed_roles_per_user(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client, hass_admin_user, guest_user
) -> None:
    """Admins and unrestricted users get every settable role; a guest only its list."""
    other = await hass.auth.async_create_user("Other", group_ids=[GROUP_ID_USER])
    restricted_overlay = await hass.auth.async_create_user("Child", group_ids=[GROUP_ID_USER])
    await setup_entry(
        hass,
        freezer,
        {
            "user_rules": {
                guest_user.id: {"mode": "allow_list", "roles": ["home", "night"]},
                other.id: {"mode": "unrestricted"},
                restricted_overlay.id: {"mode": "allow_list", "roles": ["guest"]},
            }
        },
    )
    admin = await _allowed(await _client(hass, hass_ws_client, hass_admin_user))
    assert _ids(admin["modes"]) == ["home", "night", "away", "vacation"]
    assert _ids(admin["overlays"]) == ["guest", "dnd"]
    assert admin["can_set_auto"] is True
    assert admin["modes"][0] == {
        "id": "home",
        "name": "Home",
        "type": "home",
        "icon": "mdi:home",
    }

    assert await _allowed(await _client(hass, hass_ws_client, other)) == admin

    guest = await _allowed(await _client(hass, hass_ws_client, guest_user))
    assert _ids(guest["modes"]) == ["home", "night"]
    assert guest["overlays"] == []
    assert guest["can_set_auto"] is False

    child = await _allowed(await _client(hass, hass_ws_client, restricted_overlay))
    assert child["modes"] == []
    assert _ids(child["overlays"]) == ["guest"]


async def test_allowed_roles_never_leaks_other_users_or_actions(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client, guest_user, hass_admin_user
) -> None:
    """The reply holds no user ids, rules, actions or notification settings."""
    await setup_entry(
        hass,
        freezer,
        {
            "user_rules": {
                guest_user.id: {"mode": "allow_list", "roles": ["home"]},
                hass_admin_user.id: {"mode": "unrestricted"},
            },
            "notify": {"rules": [{"event": "any_change", "targets": ["notify.secret_phone"]}]},
        },
    )
    raw = json.dumps(await _allowed(await _client(hass, hass_ws_client, guest_user)))
    for forbidden in (hass_admin_user.id, guest_user.id, "allow_list", "notify", "secret_phone"):
        assert forbidden not in raw
    assert "enter_actions" not in raw


async def test_allowed_roles_follow_the_select_options(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client, hass_admin_user
) -> None:
    """Disabled roles are never offered; the list matches the select entity options."""
    entry = make_entry(derived=True)
    roles = [
        {**r, "enabled": False} if r["id"] == "vacation" else r for r in entry.options["roles"]
    ]
    await setup_entry(hass, freezer, {"roles": roles}, derived=True)
    result = await _allowed(await _client(hass, hass_ws_client, hass_admin_user))
    assert "vacation" not in _ids(result["modes"])
    state = hass.states.get("select.home_mode")
    assert [m["name"] for m in result["modes"]] == state.attributes["options"]


async def test_allowed_roles_not_loaded(hass: HomeAssistant, hass_ws_client) -> None:
    """A clear not_found error is returned when the integration has no loaded entry."""
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "home_modes/allowed_roles"})
    reply = await client.receive_json()
    assert reply["success"] is False
    assert reply["error"]["code"] == "not_found"


async def test_guest_cannot_bypass_the_card(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """Whatever a card shows, services and entities deny roles outside the allow-list."""
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    uid = guest_user.id
    denied = [
        ("set_mode", {"mode": "night"}),
        ("set_mode", {"mode": "Night"}),
        ("set_temporary", {"mode": "night", "duration": "00:30:00"}),
        ("set_overlay", {"overlay": "guest", "active": True}),
        ("set_auto", {}),
    ]
    for service, payload in denied:
        with pytest.raises(HomeAssistantError):
            await call(hass, service, payload, user_id=uid)
    # Entities: the select and an overlay switch, called like a card or a script would.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.home_mode", "option": "Night"},
            blocking=True,
            context=Context(user_id=uid),
        )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.home_mode_overlay_guest"},
            blocking=True,
            context=Context(user_id=uid),
        )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.home_mode_auto"},
            blocking=True,
            context=Context(user_id=uid),
        )
    assert primary(entry) == "home"
    assert entry.runtime_data.coordinator.data.overlays == ()
    # The allowed role still works for the same user.
    await call(hass, "set_mode", {"mode": "home"}, user_id=uid)


async def test_guest_card_config_cannot_widen_server_list(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client, guest_user
) -> None:
    """The server list is the upper bound: nothing outside it is ever sent to a guest."""
    await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    result = await _allowed(await _client(hass, hass_ws_client, guest_user))
    assert _ids(result["modes"]) == ["home"]  # a card asking for "night" cannot list it


async def test_async_checks_match_pure_checks(hass: HomeAssistant, hass_admin_user) -> None:
    """The async checks (used by the engine) give the same answer as the pure ones."""
    guest = await hass.auth.async_create_user("G", group_ids=[GROUP_ID_USER])
    admin = hass_admin_user
    guest_rule = UserRule(UserRuleMode.ALLOW_LIST, frozenset({"home"}))
    for user, is_admin, rule in (
        (admin, True, guest_rule),
        (guest, False, guest_rule),
        (guest, False, None),
        (guest, False, UserRule(UserRuleMode.UNRESTRICTED)),
    ):
        rules = {user.id: rule} if rule else {}
        for role in ("home", "night"):
            decision = await async_check_role(hass, rules, user.id, role)
            assert decision.allowed == role_allowed(is_admin, rule, role)
        auto = await async_check_auto_control(hass, rules, user.id)
        assert auto.allowed == auto_control_allowed(is_admin, rule)


SCRIPTS = {
    "script": {
        "home_mode_home": {
            "sequence": [{"action": "home_modes.set_mode", "data": {"mode": "home"}}]
        },
        "home_mode_night": {
            "sequence": [{"action": "home_modes.set_mode", "data": {"mode": "night"}}]
        },
    }
}


async def test_script_started_by_a_guest_keeps_the_guests_limits(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user, hass_admin_user
) -> None:
    """A docs/companion-apps.md script run by a guest is denied outside the allow-list.

    The user id travels from the script call into the service call inside the script, so the
    integration checks the guest, not "no user". The same script run by an admin works.
    """
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    assert await async_setup_component(hass, "script", SCRIPTS)
    await hass.async_block_till_done()
    assert primary(entry) == "home"

    # Guest: the script for a role outside the list fails and changes nothing.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "script",
            "home_mode_night",
            blocking=True,
            context=Context(user_id=guest_user.id),
        )
    assert primary(entry) == "home"
    denied = [e for e in entry.runtime_data.history.entries if e["kind"] == "denied"]
    assert denied
    assert denied[-1]["user_id"] == guest_user.id
    assert denied[-1]["role"] == "night"

    # Guest: the script for an allowed role works.
    await hass.services.async_call(
        "script", "home_mode_home", blocking=True, context=Context(user_id=guest_user.id)
    )
    assert primary(entry) == "home"

    # Admin: the very same script is allowed.
    await hass.services.async_call(
        "script", "home_mode_night", blocking=True, context=Context(user_id=hass_admin_user.id)
    )
    assert primary(entry) == "night"
