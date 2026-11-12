"""Tests for the services, including how user contexts propagate."""

from __future__ import annotations

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_modes.const import CONF_USER_RULES, DOMAIN, EVENT_CHANGED, EVENT_DENIED

from .conftest import make_entry


async def test_set_mode_by_id_and_name(hass: HomeAssistant, entry) -> None:
    """set_mode accepts role ids and names, case-insensitively."""
    await hass.services.async_call(DOMAIN, "set_mode", {"mode": "night"}, blocking=True)
    assert entry.runtime_data.coordinator.data.primary == "night"
    await hass.services.async_call(DOMAIN, "set_mode", {"mode": " AWAY "}, blocking=True)
    assert entry.runtime_data.coordinator.data.primary == "away"
    # Setting the same mode again is a no-op.
    await hass.services.async_call(DOMAIN, "set_mode", {"mode": "away"}, blocking=True)


async def test_set_mode_errors(hass: HomeAssistant, entry) -> None:
    """Unknown, wrong-kind and disabled roles raise validation errors."""
    with pytest.raises(ServiceValidationError, match="Unknown mode"):
        await hass.services.async_call(DOMAIN, "set_mode", {"mode": "nope"}, blocking=True)
    with pytest.raises(ServiceValidationError, match="wrong kind"):
        await hass.services.async_call(DOMAIN, "set_mode", {"mode": "guest"}, blocking=True)
    with pytest.raises(ServiceValidationError, match="disabled"):
        await hass.services.async_call(DOMAIN, "set_mode", {"mode": "all_home"}, blocking=True)
    with pytest.raises(ServiceValidationError, match="wrong kind"):
        await hass.services.async_call(
            DOMAIN, "set_overlay", {"overlay": "home", "active": True}, blocking=True
        )


async def test_set_overlay(hass: HomeAssistant, entry) -> None:
    """set_overlay toggles overlays by id or name."""
    await hass.services.async_call(
        DOMAIN, "set_overlay", {"overlay": "Do not disturb", "active": True}, blocking=True
    )
    assert entry.runtime_data.coordinator.data.overlays == ("dnd",)
    await hass.services.async_call(
        DOMAIN, "set_overlay", {"overlay": "dnd", "active": False}, blocking=True
    )
    assert entry.runtime_data.coordinator.data.overlays == ()


async def test_service_without_loaded_entry(hass: HomeAssistant) -> None:
    """Services fail with a clear error when no entry is loaded."""
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError, match="not set up"):
        await hass.services.async_call(DOMAIN, "set_mode", {"mode": "night"}, blocking=True)


async def _guest_entry(hass: HomeAssistant, guest):
    config_entry = make_entry(
        options={CONF_USER_RULES: {guest.id: {"mode": "allow_list", "roles": ["home"]}}}
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    return config_entry


async def test_service_enforces_permissions(hass: HomeAssistant, guest_user) -> None:
    """A guest calling the service directly is denied server-side."""
    guest, config_entry = guest_user, await _guest_entry(hass, guest_user)
    denied = async_capture_events(hass, EVENT_DENIED)
    with pytest.raises(HomeAssistantError, match="not allowed"):
        await hass.services.async_call(
            DOMAIN, "set_mode", {"mode": "night"}, blocking=True, context=Context(user_id=guest.id)
        )
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator.data.primary == "home"
    assert len(denied) == 1


async def test_context_propagates_through_scripts(hass: HomeAssistant, guest_user) -> None:
    """FINDING: a user's context reaches the service handler through a script,
    so the allow-list applies to scripts the guest runs."""
    guest, config_entry = guest_user, await _guest_entry(hass, guest_user)
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "go_night": {
                    "sequence": [{"action": "home_modes.set_mode", "data": {"mode": "night"}}]
                }
            }
        },
    )
    denied = async_capture_events(hass, EVENT_DENIED)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "script", "go_night", {}, blocking=True, context=Context(user_id=guest.id)
        )
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator.data.primary == "home"
    assert denied[0].data["user_id"] == guest.id


async def test_context_is_lost_through_automations(hass: HomeAssistant, guest_user) -> None:
    """FINDING (known limitation): an automation triggered by a guest runs with
    no user id, so the allow-list does not apply to it. The automation's context
    only keeps a parent_id pointing at the triggering context."""
    guest, config_entry = guest_user, await _guest_entry(hass, guest_user)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "trigger": {"platform": "event", "event_type": "guest_pressed"},
                "action": {"action": "home_modes.set_mode", "data": {"mode": "night"}},
            }
        },
    )
    changed = async_capture_events(hass, EVENT_CHANGED)
    trigger_context = Context(user_id=guest.id)
    hass.bus.async_fire("guest_pressed", context=trigger_context)
    await hass.async_block_till_done()

    assert config_entry.runtime_data.coordinator.data.primary == "night"
    assert changed[0].data["user_id"] is None
    assert changed[0].context.user_id is None
    assert changed[0].context.parent_id == trigger_context.id
