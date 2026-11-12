"""Tests for the data models."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.home_modes.models import (
    SOURCE_RANKS,
    ChangeSource,
    HomeModesState,
    Override,
    Role,
    RoleKind,
    RoleType,
    TriggerInfo,
    UnknownPresenceProvider,
    role_type_from_id,
    validate_roles,
)


def test_role_types_and_kinds() -> None:
    """Role ids map to types and kinds."""
    assert role_type_from_id("custom_7") is RoleType.CUSTOM
    assert Role("home", "Home").kind is RoleKind.PRIMARY
    assert Role("custom_3", "Cinema").kind is RoleKind.PRIMARY
    assert Role("guest", "Guest").kind is RoleKind.OVERLAY
    assert Role("all_home", "All home").kind is RoleKind.DERIVED
    assert Role("all_home", "All home").selectable_primary
    assert not Role("dnd", "DND").selectable_primary
    with pytest.raises(ValueError):
        role_type_from_id("custom_x")
    with pytest.raises(ValueError):
        Role.from_dict({"id": "bogus", "name": "x"})


def test_role_round_trip() -> None:
    """Roles serialize and ignore unknown keys."""
    role = Role.from_dict({"id": "night", "name": "Sleep", "enabled": False, "x": 1})
    assert role == Role("night", "Sleep", False)
    assert Role.from_dict(role.to_dict()) == role


def test_validate_roles() -> None:
    """Role validation reports the first problem."""
    ok = [Role("home", "Home"), Role("guest", "Guest")]
    assert validate_roles(ok) is None
    assert validate_roles([Role("home", " ")]) == "name_required"
    assert validate_roles([Role("home", "A"), Role("night", "a")]) == "name_exists"
    assert validate_roles([Role("home", "Home", False), Role("guest", "G")]) == "no_primary"
    assert validate_roles([Role("home", "Home", False), Role("all_home", "A")]) == "no_primary"


def test_source_ranks() -> None:
    """The rank table follows the documented order."""
    r = SOURCE_RANKS
    assert r[ChangeSource.SYSTEM] < r[ChangeSource.MANUAL]
    assert r[ChangeSource.MANUAL] == r[ChangeSource.ALARMO] == r[ChangeSource.EXPIRY]
    assert r[ChangeSource.MANUAL] < r[ChangeSource.SCHEDULE] < r[ChangeSource.SENSOR]
    assert r[ChangeSource.SENSOR] < r[ChangeSource.PRESENCE]


def test_override_activity() -> None:
    """Overrides expire."""
    now = dt_util.utcnow()
    assert Override("manual").is_active(now)
    assert Override("manual", now + timedelta(hours=1)).is_active(now)
    assert not Override("manual", now - timedelta(seconds=1)).is_active(now)
    assert Override.from_dict(Override("manual", now).to_dict()) == Override("manual", now)


def test_state_round_trip_and_corruption() -> None:
    """State survives serialization; corrupt data raises."""
    now = dt_util.utcnow()
    state = HomeModesState(
        primary="night",
        since=now,
        previous="home",
        overlays=("guest",),
        override=Override("manual", now + timedelta(hours=1)),
        last_trigger=TriggerInfo("manual", "r"),
        auto_enabled=False,
    )
    assert HomeModesState.from_dict(state.to_dict()) == state
    minimal = HomeModesState.from_dict({"primary": "home", "since": now.isoformat()})
    assert minimal.override is None
    assert minimal.last_trigger is None
    assert minimal.auto_enabled
    with pytest.raises(KeyError):
        HomeModesState.from_dict({"since": now.isoformat()})
    with pytest.raises(ValueError):
        HomeModesState.from_dict({"primary": "home", "since": "nope"})


def test_unknown_presence() -> None:
    """The default provider reports unknown."""
    provider = UnknownPresenceProvider()
    assert provider.all_home is None
    assert provider.all_away is None
    provider.async_add_listener(lambda: None)()


def test_role_actions_roundtrip() -> None:
    """Enter/exit actions survive to_dict/from_dict; empty actions are not stored."""
    from custom_components.home_modes.models import Role

    role = Role(
        "night",
        "Night",
        True,
        enter_actions=({"action": "light.turn_off", "target": {"entity_id": "light.x"}},),
        exit_actions=({"delay": {"seconds": 1}},),
    )
    restored = Role.from_dict(role.to_dict())
    assert restored == role
    assert "enter_actions" not in Role("home", "Home").to_dict()
    assert Role.from_dict({"id": "home", "name": "Home"}).enter_actions == ()
