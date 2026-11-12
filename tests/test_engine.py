"""Tests for the change pipeline."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.home_modes.const import (
    CONF_ROLES,
    EVENT_CHANGED,
    EVENT_DENIED,
)
from custom_components.home_modes.models import (
    Change,
    ChangeKind,
    ChangeSource,
    ChangeStatus,
    Override,
    PipelineStage,
)

from .conftest import make_entry


async def test_set_primary_applies_and_fires_event(hass: HomeAssistant, entry) -> None:
    """A primary change updates state and fires home_modes_changed."""
    engine = entry.runtime_data.engine
    events = async_capture_events(hass, EVENT_CHANGED)
    ctx = Context()

    result = await engine.async_set_primary(
        "night", ChangeSource.MANUAL, rule="bedtime", context=ctx
    )
    await hass.async_block_till_done()

    assert result.status is ChangeStatus.APPLIED
    state = entry.runtime_data.coordinator.data
    assert state.primary == "night"
    assert state.previous == "home"
    assert state.last_trigger.source == "manual"
    assert state.last_trigger.rule == "bedtime"
    assert len(events) == 1
    assert events[0].data == {
        "kind": "primary",
        "from": "home",
        "to": "night",
        "role": "night",
        "active": True,
        "overlays": [],
        "source": "manual",
        "rule": "bedtime",
        "user_id": None,
    }
    assert events[0].context.id == ctx.id


async def test_unchanged_unknown_disabled_and_invalid(hass: HomeAssistant, entry) -> None:
    """Requests that cannot be applied are reported, not raised."""
    engine = entry.runtime_data.engine
    events = async_capture_events(hass, EVENT_CHANGED)

    assert (
        await engine.async_set_primary("home", ChangeSource.MANUAL)
    ).status is ChangeStatus.UNCHANGED
    unknown = await engine.async_set_primary("bogus", ChangeSource.MANUAL)
    assert (unknown.status, unknown.reason) == (ChangeStatus.REJECTED, "unknown_role")
    disabled = await engine.async_set_primary("all_home", ChangeSource.MANUAL)
    assert (disabled.status, disabled.reason) == (ChangeStatus.REJECTED, "role_disabled")
    off = await engine.async_set_overlay("night", False, ChangeSource.MANUAL)
    assert off.reason == "cannot_deactivate_primary"
    await hass.async_block_till_done()
    assert not events


async def test_overlays_stack_and_do_not_touch_primary(hass: HomeAssistant, entry) -> None:
    """Overlays toggle independently and keep primary bookkeeping."""
    engine = entry.runtime_data.engine
    coordinator = entry.runtime_data.coordinator
    events = async_capture_events(hass, EVENT_CHANGED)
    since = coordinator.data.since

    on = await engine.async_set_overlay("guest", True, ChangeSource.MANUAL)
    assert on.change.kind is ChangeKind.OVERLAY
    assert (on.change.from_role, on.change.to_role) == (None, "guest")
    await engine.async_set_overlay("dnd", True, ChangeSource.MANUAL)
    assert coordinator.data.overlays == ("guest", "dnd")
    assert coordinator.data.primary == "home"
    assert coordinator.data.since == since
    assert (
        await engine.async_set_overlay("dnd", True, ChangeSource.MANUAL)
    ).status is ChangeStatus.UNCHANGED

    off = await engine.async_set_overlay("guest", False, ChangeSource.MANUAL)
    assert (off.change.from_role, off.change.to_role) == ("guest", None)
    await engine.async_set_primary("night", ChangeSource.MANUAL)
    assert coordinator.data.overlays == ("dnd",)
    await hass.async_block_till_done()
    assert events[-1].data["overlays"] == ["dnd"]


async def test_override_priority(hass: HomeAssistant, entry) -> None:
    """Lower ranks are ignored while an override is active."""
    from dataclasses import replace

    engine = entry.runtime_data.engine
    coordinator = entry.runtime_data.coordinator
    now = dt_util.utcnow()
    coordinator.async_apply_state(
        replace(coordinator.data, override=Override("manual", now + timedelta(hours=1)))
    )

    for source in (ChangeSource.SCHEDULE, ChangeSource.SENSOR, ChangeSource.PRESENCE):
        result = await engine.async_set_primary("night", source)
        assert (result.status, result.reason) == (ChangeStatus.IGNORED, "override_active")
    assert coordinator.data.primary == "home"

    # Same or higher rank and system changes pass.
    assert (
        await engine.async_set_primary("night", ChangeSource.ALARMO)
    ).status is ChangeStatus.APPLIED
    assert (
        await engine.async_set_primary("away", ChangeSource.SYSTEM)
    ).status is ChangeStatus.APPLIED

    # A schedule override only blocks sensor and presence.
    coordinator.async_apply_state(
        replace(coordinator.data, override=Override("schedule", now + timedelta(hours=1)))
    )
    assert (
        await engine.async_set_primary("home", ChangeSource.SCHEDULE)
    ).status is ChangeStatus.APPLIED
    assert (
        await engine.async_set_primary("night", ChangeSource.PRESENCE)
    ).status is ChangeStatus.IGNORED


async def test_expired_or_unknown_override_does_not_block(hass: HomeAssistant, entry) -> None:
    """Expired overrides and overrides with an unknown source are ignored."""
    from dataclasses import replace

    engine = entry.runtime_data.engine
    coordinator = entry.runtime_data.coordinator
    past = dt_util.utcnow() - timedelta(minutes=1)
    coordinator.async_apply_state(replace(coordinator.data, override=Override("manual", past)))
    assert (
        await engine.async_set_primary("night", ChangeSource.PRESENCE)
    ).status is ChangeStatus.APPLIED
    coordinator.async_apply_state(
        replace(coordinator.data, override=Override("bogus", dt_util.utcnow() + timedelta(hours=1)))
    )
    assert (
        await engine.async_set_primary("away", ChangeSource.PRESENCE)
    ).status is ChangeStatus.APPLIED


async def test_hooks_run_in_order_and_failures_are_isolated(hass: HomeAssistant, entry) -> None:
    """Hooks run around the state change; a failing hook does not abort it."""
    engine = entry.runtime_data.engine
    coordinator = entry.runtime_data.coordinator
    seen: list[tuple[str, str]] = []

    def make_hook(stage: PipelineStage):
        async def hook(change: Change) -> None:
            # Record the primary visible to the hook at this stage.
            seen.append((stage.value, coordinator.data.primary))

        return hook

    unregister = [engine.async_register_hook(stage, make_hook(stage)) for stage in PipelineStage]
    failing = AsyncMock(side_effect=RuntimeError("boom"))
    engine.async_register_hook(PipelineStage.EXIT_ACTIONS, failing)

    result = await engine.async_set_primary("night", ChangeSource.MANUAL)
    assert result.status is ChangeStatus.APPLIED
    assert seen == [
        ("exit_actions", "home"),
        ("enter_actions", "night"),
        ("history", "night"),
        ("notify", "night"),
        ("alarmo", "night"),
    ]
    failing.assert_awaited_once()

    for remove in unregister:
        remove()
        remove()  # removing twice is harmless
    seen.clear()
    await engine.async_set_primary("home", ChangeSource.MANUAL)
    assert seen == []


async def test_auto_flag(hass: HomeAssistant, entry) -> None:
    """The auto flag is stored without a mode change."""
    engine = entry.runtime_data.engine
    coordinator = entry.runtime_data.coordinator
    assert (await engine.async_set_auto(True)).status is ChangeStatus.UNCHANGED
    assert (await engine.async_set_auto(False)).status is ChangeStatus.APPLIED
    assert coordinator.data.auto_enabled is False


async def test_denied_fires_event(hass: HomeAssistant, guest_user) -> None:
    """Denied changes are logged and fire home_modes_denied."""
    guest = guest_user
    config_entry = make_entry(
        options={"user_rules": {guest.id: {"mode": "allow_list", "roles": ["home"]}}}
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    engine = config_entry.runtime_data.engine
    denied = async_capture_events(hass, EVENT_DENIED)
    changed = async_capture_events(hass, EVENT_CHANGED)
    ctx = Context(user_id=guest.id)

    result = await engine.async_set_primary("night", ChangeSource.MANUAL, context=ctx)
    assert (result.status, result.reason) == (ChangeStatus.DENIED, "not_in_allow_list")
    auto = await engine.async_set_auto(False, ctx)
    assert auto.status is ChangeStatus.DENIED
    # Non-manual sources are not user sources and skip the permission check.
    assert (
        await engine.async_set_primary("night", ChangeSource.SCHEDULE, context=ctx)
    ).status is ChangeStatus.APPLIED
    await hass.async_block_till_done()

    assert [e.data for e in denied] == [
        {"role": "night", "user_id": guest.id, "source": "manual", "reason": "not_in_allow_list"},
        {"role": None, "user_id": guest.id, "source": "manual", "reason": "allow_list_user"},
    ]
    assert len(changed) == 1


async def test_reconcile_falls_back_to_previous_then_first(hass: HomeAssistant, entry) -> None:
    """Disabling the active primary switches to previous, else first enabled."""
    engine = entry.runtime_data.engine
    await engine.async_set_primary("night", ChangeSource.MANUAL)
    await hass.async_block_till_done()

    def with_enabled(roles: list[dict], disabled: set[str]) -> list[dict]:
        return [{**r, "enabled": r["enabled"] and r["id"] not in disabled} for r in roles]

    options = entry.options
    hass.config_entries.async_update_entry(
        entry, options={CONF_ROLES: with_enabled(options[CONF_ROLES], {"night"})}
    )
    events = async_capture_events(hass, EVENT_CHANGED)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert coordinator.data.primary == "home"  # previous
    assert coordinator.data.last_trigger.source == "system"
    assert coordinator.data.last_trigger.rule == "role_disabled"
    assert [e.data["source"] for e in events] == ["system"]

    # Now disable home too while away is active with previous == home.
    await entry.runtime_data.engine.async_set_primary("away", ChangeSource.MANUAL)
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_ROLES: with_enabled(entry.options[CONF_ROLES], {"away", "home", "night"})},
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.data.primary == "vacation"  # first enabled


async def test_reconcile_switches_off_disabled_overlay(hass: HomeAssistant, entry) -> None:
    """A disabled or removed overlay is turned off at startup."""
    engine = entry.runtime_data.engine
    await engine.async_set_overlay("guest", True, ChangeSource.MANUAL)
    roles = [
        {**r, "enabled": r["enabled"] and r["id"] != "guest"} for r in entry.options[CONF_ROLES]
    ]
    hass.config_entries.async_update_entry(entry, options={CONF_ROLES: roles})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.data.overlays == ()

    # An overlay id that no longer exists at all is dropped silently.
    await entry.runtime_data.engine.async_set_overlay("dnd", True, ChangeSource.MANUAL)
    roles = [r for r in entry.options[CONF_ROLES] if r["id"] != "dnd"]
    hass.config_entries.async_update_entry(entry, options={CONF_ROLES: roles})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.data.overlays == ()


async def test_time_based_tick_is_irrelevant(hass: HomeAssistant, entry) -> None:
    """The coordinator never polls."""
    coordinator = entry.runtime_data.coordinator
    before = coordinator.data
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=2))
    await hass.async_block_till_done()
    assert coordinator.data is before
    assert await coordinator._async_update_data() is before
