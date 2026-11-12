"""revert, set_temporary, set_auto, the auto switch and permission denial."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_modes.const import EVENT_CHANGED, EVENT_DENIED
from custom_components.home_modes.models import PipelineStage, Role

from .helpers import (
    NIGHT_WINDOW,
    advance,
    call,
    data,
    presence_options,
    primary,
    roles_without,
    setup_entry,
)

EVENING = "2026-11-12 21:59:00+00:00"
HOME2 = {"person.anna": "home", "person.ben": "home"}


# --- set_temporary ---------------------------------------------------------------


async def test_set_temporary_expires_to_previous(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """set_temporary changes the mode and reverts with source temporary_expiry."""
    entry = await setup_entry(hass, freezer)
    events = async_capture_events(hass, EVENT_CHANGED)
    await call(
        hass, "set_temporary", {"mode": "away", "duration": {"minutes": 10}}, hass_admin_user.id
    )
    assert primary(entry) == "away"
    assert data(entry).temporary.revert_to == "home"
    assert data(entry).override is not None  # auto-rules wait for the revert
    await advance(hass, freezer, minutes=9)
    assert primary(entry) == "away"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "home"
    assert (data(entry).last_trigger.source, data(entry).last_trigger.rule) == (
        "temporary_expiry",
        "temporary_expiry",
    )
    assert data(entry).temporary is None
    assert data(entry).override is None
    assert [e.data["source"] for e in events] == ["manual", "temporary_expiry"]
    assert hass.states.get("sensor.home_mode_trigger_reason").state == "temporary_expiry"


async def test_set_temporary_blocks_auto_rules(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """Auto-rules are ignored while a temporary mode runs."""
    entry = await setup_entry(hass, freezer, {"night": NIGHT_WINDOW}, start=EVENING)
    await call(
        hass, "set_temporary", {"mode": "away", "duration": {"hours": 1}}, hass_admin_user.id
    )
    await advance(hass, freezer, minutes=5)  # 22:04: night window started
    assert primary(entry) == "away"
    await advance(hass, freezer, hours=1)
    assert primary(entry) == "home"  # reverted; not re-evaluated against the schedule


async def test_manual_change_cancels_temporary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """Choosing another mode during a temporary mode cancels the revert."""
    entry = await setup_entry(hass, freezer)
    await call(
        hass, "set_temporary", {"mode": "away", "duration": {"minutes": 10}}, hass_admin_user.id
    )
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    assert data(entry).temporary is None
    await advance(hass, freezer, minutes=20)
    assert primary(entry) == "night"


async def test_nested_temporary_keeps_original_target(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A second set_temporary keeps the first revert target (home)."""
    entry = await setup_entry(hass, freezer)
    await call(
        hass, "set_temporary", {"mode": "away", "duration": {"minutes": 30}}, hass_admin_user.id
    )
    await call(
        hass, "set_temporary", {"mode": "night", "duration": {"minutes": 5}}, hass_admin_user.id
    )
    assert data(entry).temporary.revert_to == "home"
    await advance(hass, freezer, minutes=6)
    assert primary(entry) == "home"
    await advance(hass, freezer, minutes=40)
    assert primary(entry) == "home"  # no stale timer from the first temporary


async def test_temporary_to_current_mode_is_unchanged(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Setting the current mode temporarily changes nothing."""
    entry = await setup_entry(hass, freezer)
    await call(hass, "set_temporary", {"mode": "home", "duration": {"minutes": 5}})
    assert data(entry).temporary is None


async def test_temporary_revert_target_disabled_falls_back(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """If the stored revert target was disabled, the first enabled primary is used."""
    entry = await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "night"})
    await call(hass, "set_temporary", {"mode": "away", "duration": {"minutes": 5}})
    coordinator = entry.runtime_data.coordinator
    coordinator.roles = tuple(
        Role(r.id, r.name, r.id != "night" and r.enabled) for r in coordinator.roles
    )
    await advance(hass, freezer, minutes=6)
    assert primary(entry) == "home"  # first enabled kind-primary role


async def test_derived_target_never_used_as_fallback(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The fallback after an expiry is a kind-primary role, never all_home/all_away."""
    entry = await setup_entry(hass, freezer, derived=True)
    engine = entry.runtime_data.engine
    assert engine._fallback_primary("all_home").id == "home"
    assert engine._fallback_primary("guest").id == "home"
    assert engine._fallback_primary(None).id == "home"
    assert engine._fallback_primary("night").id == "night"


async def test_set_temporary_errors(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Disabled, overlay and unknown targets are rejected; duration must be positive."""
    await setup_entry(hass, freezer, {"roles": roles_without("night")})
    with pytest.raises(ServiceValidationError, match="disabled"):
        await call(hass, "set_temporary", {"mode": "night", "duration": {"minutes": 5}})
    with pytest.raises(ServiceValidationError, match="wrong kind"):
        await call(hass, "set_temporary", {"mode": "guest", "duration": {"minutes": 5}})
    with pytest.raises(ServiceValidationError, match="Unknown"):
        await call(hass, "set_temporary", {"mode": "nope", "duration": {"minutes": 5}})
    with pytest.raises(Exception, match="longer than zero"):
        await call(hass, "set_temporary", {"mode": "away", "duration": {"seconds": 0}})


# --- revert ----------------------------------------------------------------------


async def test_revert_chain(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """revert goes back to the previous mode; repeating it toggles the last two."""
    entry = await setup_entry(hass, freezer)
    with pytest.raises(ServiceValidationError, match="previous"):
        await call(hass, "revert")
    await call(hass, "set_mode", {"mode": "night"})
    await call(hass, "set_mode", {"mode": "away"})
    await call(hass, "revert")
    assert primary(entry) == "night"
    assert data(entry).last_trigger.rule == "revert"
    await call(hass, "revert")
    assert primary(entry) == "away"
    await call(hass, "revert")
    assert primary(entry) == "night"


async def test_revert_to_disabled_previous_is_rejected(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A previous mode that is disabled now cannot be a target."""
    entry = await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "night"})
    coordinator = entry.runtime_data.coordinator
    coordinator.roles = tuple(
        Role(r.id, r.name, r.id != "home" and r.enabled) for r in coordinator.roles
    )
    with pytest.raises(ServiceValidationError, match="disabled"):
        await call(hass, "revert")


# --- set_auto and the auto switch --------------------------------------------------


async def test_auto_switch_off_and_on(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Off: no auto change. On: re-evaluated immediately."""
    entry = await setup_entry(hass, freezer, {"night": NIGHT_WINDOW}, start=EVENING)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await advance(hass, freezer, minutes=5)  # 22:04, window started
    assert primary(entry) == "home"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    assert data(entry).last_trigger.rule == "night_time_window"


async def test_auto_off_ignores_presence(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With the switch off presence never changes the mode."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=48)
    assert primary(entry) == "home"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await hass.async_block_till_done()
    assert primary(entry) == "vacation"


async def test_set_auto_with_auto_off_only_clears_override(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """set_auto clears the override; it does not evaluate while auto-rules are off."""
    entry = await setup_entry(hass, freezer, {"night": NIGHT_WINDOW}, start=EVENING)
    await call(hass, "set_mode", {"mode": "away"}, hass_admin_user.id)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await call(hass, "set_auto", user_id=hass_admin_user.id)
    assert data(entry).override is None
    assert primary(entry) == "away"


# --- permissions on the new services ---------------------------------------------


async def test_permission_denial_on_new_services(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """Allow-list users are denied outside their list on every new service."""
    options = {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home", "away"]}}}
    entry = await setup_entry(hass, freezer, options)
    denied = async_capture_events(hass, EVENT_DENIED)

    with pytest.raises(HomeAssistantError, match="not allowed"):
        await call(
            hass, "set_temporary", {"mode": "night", "duration": {"minutes": 5}}, guest_user.id
        )
    await call(hass, "set_mode", {"mode": "away"}, guest_user.id)
    await call(hass, "set_mode", {"mode": "home"}, guest_user.id)
    await call(hass, "set_mode", {"mode": "away"})  # previous becomes home... then night:
    await call(hass, "set_mode", {"mode": "night"})
    assert primary(entry) == "night"
    await call(hass, "set_mode", {"mode": "away"})
    # previous is night, which the guest may not set
    with pytest.raises(HomeAssistantError, match="not allowed"):
        await call(hass, "revert", user_id=guest_user.id)
    with pytest.raises(HomeAssistantError, match="not allowed"):
        await call(hass, "set_auto", user_id=guest_user.id)
    assert primary(entry) == "away"
    assert [e.data["reason"] for e in denied] == [
        "not_in_allow_list",
        "not_in_allow_list",
        "allow_list_user",
    ]
    # Allowed role: temporary works for the guest.
    await call(hass, "set_temporary", {"mode": "home", "duration": {"minutes": 5}}, guest_user.id)
    assert primary(entry) == "home"
    assert data(entry).override is not None


async def test_set_mode_override_false_for_user_blocks_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """override: false from a user ranks manual but leaves auto-rules free."""
    entry = await setup_entry(hass, freezer, {"night": NIGHT_WINDOW}, start=EVENING)
    await call(
        hass,
        "set_mode",
        {"mode": "custom_x"} if False else {"mode": "home", "override": False},
        hass_admin_user.id,
    )
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "night"


# --- events and hooks ---------------------------------------------------------------


async def test_event_payload_overlay_and_primary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Both kinds carry kind, from, to, role, active, overlays, source, rule, user_id."""
    await setup_entry(hass, freezer)
    events = async_capture_events(hass, EVENT_CHANGED)
    await call(hass, "set_mode", {"mode": "night"})
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await hass.async_block_till_done()
    primary_event, on, off = (e.data for e in events)
    assert primary_event["kind"] == "primary"
    assert primary_event["active"] is True
    assert (on["kind"], on["from"], on["to"], on["role"], on["active"]) == (
        "overlay",
        None,
        "guest",
        "guest",
        True,
    )
    assert (off["from"], off["to"], off["role"], off["active"]) == ("guest", None, "guest", False)
    assert set(on) == {
        "kind",
        "from",
        "to",
        "role",
        "active",
        "overlays",
        "source",
        "rule",
        "user_id",
    }


async def test_history_hook_receives_auto_rule_name(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The history hook sees the rule name of every auto change."""
    entry = await setup_entry(hass, freezer, {"night": NIGHT_WINDOW}, start=EVENING)
    seen: list[tuple[str, str | None]] = []

    async def hook(change) -> None:
        seen.append((change.source.value, change.rule))

    entry.runtime_data.engine.async_register_hook(PipelineStage.HISTORY, hook)
    await advance(hass, freezer, minutes=2)
    assert seen == [("schedule", "night_time_window")]


# --- re-evaluation after temporary expiry and revert -------------------------------


async def _leave(hass: HomeAssistant) -> None:
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()


async def test_expiry_reevaluates_presence(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """Everybody leaves during a temporary night: the expiry ends in away, not home."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    events = async_capture_events(hass, EVENT_CHANGED)
    await call(
        hass, "set_temporary", {"mode": "night", "duration": {"hours": 1}}, hass_admin_user.id
    )
    await _leave(hass)
    await advance(hass, freezer, minutes=30)  # away delay passed but the override blocks
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=31)
    assert primary(entry) == "away"
    assert data(entry).last_trigger.rule == "presence_away"
    assert [e.data["source"] for e in events] == ["manual", "temporary_expiry", "presence"]


async def test_expiry_respects_presence_delay(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """If the away delay has not passed at expiry, the revert target stays until it does."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    await call(
        hass, "set_temporary", {"mode": "night", "duration": {"minutes": 10}}, hass_admin_user.id
    )
    await advance(hass, freezer, minutes=8)
    await _leave(hass)
    await advance(hass, freezer, minutes=3)  # expiry, away delay (4 min) not passed yet
    assert primary(entry) == "home"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "away"


async def test_expiry_with_auto_off_keeps_revert_target(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """With the auto switch off the expiry results in the revert target."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await call(
        hass, "set_temporary", {"mode": "night", "duration": {"hours": 1}}, hass_admin_user.id
    )
    await _leave(hass)
    await advance(hass, freezer, minutes=61)
    assert primary(entry) == "home"
    await advance(hass, freezer, hours=3)
    assert primary(entry) == "home"


async def test_revert_reevaluates_auto_rules(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """After a revert, a mode that auto-rules now require is applied immediately."""
    options = {**presence_options(), "override": {"until": "set_auto"}}
    entry = await setup_entry(hass, freezer, options, states=HOME2)
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    await _leave(hass)
    await call(hass, "set_mode", {"mode": "home"}, hass_admin_user.id)
    await advance(hass, freezer, minutes=10)
    assert primary(entry) == "home"  # blocked by the set_auto override
    await call(hass, "set_auto", user_id=hass_admin_user.id)  # clears + evaluates -> away
    assert primary(entry) == "away"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await call(hass, "revert")  # away -> home; auto off: no re-evaluation
    assert primary(entry) == "home"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await call(hass, "set_mode", {"mode": "night"})
    await call(hass, "revert")  # night -> home, then auto-rules say away
    assert primary(entry) == "away"
