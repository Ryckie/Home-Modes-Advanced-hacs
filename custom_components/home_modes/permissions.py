"""Server-side permission checks for Home Modes Advanced."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.core import HomeAssistant


class UserRuleMode(StrEnum):
    """How a user's rule is applied."""

    ALLOW_LIST = "allow_list"
    UNRESTRICTED = "unrestricted"


@dataclass(frozen=True, slots=True)
class UserRule:
    """Permission rule for one user."""

    mode: UserRuleMode
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Result of a permission check."""

    allowed: bool
    reason: str


def parse_user_rules(raw: Mapping[str, Any] | None) -> dict[str, UserRule]:
    """Parse stored user rules, skipping malformed entries."""
    rules: dict[str, UserRule] = {}
    for user_id, rule in (raw or {}).items():
        try:
            mode = UserRuleMode(rule["mode"])
        except KeyError, TypeError, ValueError:
            continue
        rules[str(user_id)] = UserRule(
            mode=mode, roles=frozenset(str(r) for r in rule.get("roles", []))
        )
    return rules


async def _async_lookup(hass: HomeAssistant, user_id: str) -> tuple[bool, bool]:
    """Return (user_exists, is_admin)."""
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        return False, False
    return True, user.is_admin


def role_allowed(is_admin: bool, rule: UserRule | None, role_id: str) -> bool:
    """Return whether a known user may change a role (the single source of truth).

    Admins are exempt. Users without a rule, or with an unrestricted rule, may change
    every role. Allow-list users may change only the roles on their list.
    """
    if is_admin:
        return True
    if rule is None or rule.mode is UserRuleMode.UNRESTRICTED:
        return True
    return role_id in rule.roles


def auto_control_allowed(is_admin: bool, rule: UserRule | None) -> bool:
    """Return whether a known user may use the auto switch / set_auto."""
    if is_admin:
        return True
    return rule is None or rule.mode is not UserRuleMode.ALLOW_LIST


async def async_check_role(
    hass: HomeAssistant,
    rules: Mapping[str, UserRule],
    user_id: str | None,
    role_id: str,
) -> PermissionDecision:
    """Check whether a user may change a role.

    No user id (automations, system) is allowed. Admins are exempt. Users that
    are not listed are unrestricted. Unknown users are denied (fail closed).
    """
    if not user_id:
        return PermissionDecision(True, "no_user")
    exists, is_admin = await _async_lookup(hass, user_id)
    if not exists:
        return PermissionDecision(False, "unknown_user")
    if is_admin:
        return PermissionDecision(True, "admin")
    rule = rules.get(user_id)
    if rule is None or rule.mode is UserRuleMode.UNRESTRICTED:
        return PermissionDecision(True, "unrestricted")
    if role_id in rule.roles:
        return PermissionDecision(True, "allow_list")
    return PermissionDecision(False, "not_in_allow_list")


async def async_check_auto_control(
    hass: HomeAssistant, rules: Mapping[str, UserRule], user_id: str | None
) -> PermissionDecision:
    """Check whether a user may toggle the auto-rules switch.

    Allow-list users (guests) may not; everybody else follows async_check_role.
    """
    if not user_id:
        return PermissionDecision(True, "no_user")
    exists, is_admin = await _async_lookup(hass, user_id)
    if not exists:
        return PermissionDecision(False, "unknown_user")
    if is_admin:
        return PermissionDecision(True, "admin")
    rule = rules.get(user_id)
    if rule is not None and rule.mode is UserRuleMode.ALLOW_LIST:
        return PermissionDecision(False, "allow_list_user")
    return PermissionDecision(True, "unrestricted")
