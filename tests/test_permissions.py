"""Tests for permission checks."""

from __future__ import annotations

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import HomeAssistant

from custom_components.home_modes.permissions import (
    UserRule,
    UserRuleMode,
    async_check_auto_control,
    async_check_role,
    parse_user_rules,
)


def test_parse_user_rules_skips_malformed() -> None:
    """Malformed rules are skipped."""
    rules = parse_user_rules(
        {
            "a": {"mode": "allow_list", "roles": ["night"]},
            "b": {"mode": "unrestricted"},
            "c": {"mode": "bogus"},
            "d": "nope",
            "e": {},
        }
    )
    assert rules == {
        "a": UserRule(UserRuleMode.ALLOW_LIST, frozenset({"night"})),
        "b": UserRule(UserRuleMode.UNRESTRICTED, frozenset()),
    }
    assert parse_user_rules(None) == {}


async def test_role_permissions(hass: HomeAssistant, hass_admin_user) -> None:
    """Admins are exempt, allow-list users are limited, others unrestricted."""
    guest = await hass.auth.async_create_user("Guest", group_ids=[GROUP_ID_USER])
    other = await hass.auth.async_create_user("Other", group_ids=[GROUP_ID_USER])
    rules = {
        guest.id: UserRule(UserRuleMode.ALLOW_LIST, frozenset({"home"})),
        hass_admin_user.id: UserRule(UserRuleMode.ALLOW_LIST, frozenset()),
    }

    assert (await async_check_role(hass, rules, None, "night")).reason == "no_user"
    assert (await async_check_role(hass, rules, "missing", "night")).reason == "unknown_user"
    assert (await async_check_role(hass, rules, hass_admin_user.id, "night")).reason == "admin"
    assert (await async_check_role(hass, rules, guest.id, "home")).allowed
    denied = await async_check_role(hass, rules, guest.id, "night")
    assert not denied.allowed
    assert denied.reason == "not_in_allow_list"
    assert (await async_check_role(hass, rules, other.id, "night")).reason == "unrestricted"
    rules[other.id] = UserRule(UserRuleMode.UNRESTRICTED)
    assert (await async_check_role(hass, rules, other.id, "night")).allowed


async def test_auto_control_permissions(hass: HomeAssistant, hass_admin_user) -> None:
    """Allow-list users may not toggle the auto switch."""
    guest = await hass.auth.async_create_user("Guest", group_ids=[GROUP_ID_USER])
    other = await hass.auth.async_create_user("Other", group_ids=[GROUP_ID_USER])
    rules = {guest.id: UserRule(UserRuleMode.ALLOW_LIST, frozenset({"home"}))}

    assert (await async_check_auto_control(hass, rules, None)).allowed
    assert (await async_check_auto_control(hass, rules, "missing")).reason == "unknown_user"
    assert (await async_check_auto_control(hass, rules, hass_admin_user.id)).allowed
    assert (await async_check_auto_control(hass, rules, other.id)).allowed
    denied = await async_check_auto_control(hass, rules, guest.id)
    assert not denied.allowed
    assert denied.reason == "allow_list_user"
