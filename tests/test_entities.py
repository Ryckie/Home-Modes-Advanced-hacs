"""Tests for the entities."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.home_modes.const import CONF_ROLES, CONF_USER_RULES
from custom_components.home_modes.models import ChangeSource

from .conftest import make_entry


class FakePresence:
    """Presence provider whose values tests can change."""

    def __init__(self) -> None:
        self.all_home: bool | None = None
        self.all_away: bool | None = None
        self.listeners: list = []

    def async_add_listener(self, update_callback):
        self.listeners.append(update_callback)
        return lambda: self.listeners.remove(update_callback)

    def async_start(self) -> None:
        """Tracker interface (no-op)."""

    def async_stop(self) -> None:
        """Tracker interface (no-op)."""

    def async_refresh(self) -> None:
        """Tracker interface (no-op)."""

    def set(self, all_home: bool | None, all_away: bool | None) -> None:
        self.all_home, self.all_away = all_home, all_away
        for callback in list(self.listeners):
            callback()


async def test_entity_ids_and_names(hass: HomeAssistant, entry) -> None:
    """Entity ids are stable and match the brief; names show the role names."""
    expected = {
        "select.home_mode",
        "binary_sensor.home_mode_home",
        "binary_sensor.home_mode_night",
        "binary_sensor.home_mode_away",
        "binary_sensor.home_mode_vacation",
        "binary_sensor.home_mode_guest",
        "binary_sensor.home_mode_dnd",
        "sensor.home_mode_since",
        "sensor.home_mode_previous",
        "sensor.home_mode_trigger_reason",
        "switch.home_mode_auto",
        "switch.home_mode_overlay_guest",
        "switch.home_mode_overlay_dnd",
    }
    assert {s.entity_id for s in hass.states.async_all()} == expected
    registry = er.async_get(hass)
    assert registry.async_get("binary_sensor.home_mode_dnd").original_name == "Do not disturb"
    assert (
        registry.async_get("switch.home_mode_overlay_dnd").original_name == "Do not disturb overlay"
    )
    assert registry.async_get("sensor.home_mode_since").original_name == "Since"
    assert registry.async_get("switch.home_mode_auto").original_name == "Auto"
    device = er.dr.async_get(hass).async_get(registry.async_get("select.home_mode").device_id)
    assert device.name == "Home Mode"


async def test_select(hass: HomeAssistant, entry) -> None:
    """The select lists selectable primaries by name and switches modes."""
    state = hass.states.get("select.home_mode")
    assert state.state == "Home"
    assert state.attributes["options"] == ["Home", "Night", "Away", "Vacation"]
    assert state.attributes["role"] == "home"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.home_mode", "option": "Night"},
        blocking=True,
    )
    state = hass.states.get("select.home_mode")
    assert state.state == "Night"
    assert state.attributes["role"] == "night"
    assert hass.states.get("binary_sensor.home_mode_night").state == STATE_ON
    assert hass.states.get("binary_sensor.home_mode_home").state == STATE_OFF

    # The option can also be given case-insensitively by role id.
    entity = hass.data["entity_components"]["select"].get_entity("select.home_mode")
    await entity.async_select_option("away")
    assert hass.states.get("select.home_mode").state == "Away"
    with pytest.raises(ServiceValidationError):
        await entity.async_select_option("Nope")


async def test_select_options_follow_order_and_rename(hass: HomeAssistant, entry) -> None:
    """Renaming and ordering roles changes options and displayed names."""
    roles = [dict(r) for r in entry.options[CONF_ROLES]]
    roles[0], roles[1] = roles[1], roles[0]
    next(r for r in roles if r["id"] == "night")["name"] = "Sleep"
    hass.config_entries.async_update_entry(entry, options={CONF_ROLES: roles})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("select.home_mode").attributes["options"] == [
        "Sleep",
        "Home",
        "Away",
        "Vacation",
    ]
    registry = er.async_get(hass)
    assert registry.async_get("binary_sensor.home_mode_night").original_name == "Sleep"
    # The entity id stays stable after a rename.
    assert hass.states.get("binary_sensor.home_mode_night") is not None


async def test_user_renamed_entity_name_is_kept(hass: HomeAssistant, entry) -> None:
    """A name the user set in the entity registry survives role renames."""
    registry = er.async_get(hass)
    registry.async_update_entity("binary_sensor.home_mode_night", name="Bedtime (mine)")
    roles = [dict(r) for r in entry.options[CONF_ROLES]]
    next(r for r in roles if r["id"] == "night")["name"] = "Sleep"
    hass.config_entries.async_update_entry(entry, options={CONF_ROLES: roles})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reg = registry.async_get("binary_sensor.home_mode_night")
    assert reg.name == "Bedtime (mine)"
    assert reg.original_name == "Sleep"


async def test_sensors(hass: HomeAssistant, entry) -> None:
    """Sensors follow the primary mode."""
    coordinator = entry.runtime_data.coordinator
    assert (
        hass.states.get("sensor.home_mode_since").state
        == coordinator.data.since.replace(microsecond=0).isoformat()
    )
    assert hass.states.get("sensor.home_mode_previous").state == STATE_UNKNOWN
    reason = hass.states.get("sensor.home_mode_trigger_reason")
    assert (reason.state, reason.attributes["rule"]) == ("system", "initial")

    await entry.runtime_data.engine.async_set_primary(
        "night", ChangeSource.SCHEDULE, rule="bedtime"
    )
    await hass.async_block_till_done()
    previous = hass.states.get("sensor.home_mode_previous")
    assert (previous.state, previous.attributes["role"]) == ("Home", "home")
    reason = hass.states.get("sensor.home_mode_trigger_reason")
    assert (reason.state, reason.attributes["rule"]) == ("schedule", "bedtime")

    # A previous role that no longer exists is shown by its id.
    from dataclasses import replace

    coordinator.async_apply_state(replace(coordinator.data, previous="custom_9"))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.home_mode_previous").state == "custom_9"


async def test_binary_sensors_and_overlay_switches(hass: HomeAssistant, entry) -> None:
    """Overlay switches and binary sensors reflect the overlays."""
    assert hass.states.get("binary_sensor.home_mode_guest").state == STATE_OFF
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_mode_overlay_guest"}, blocking=True
    )
    assert hass.states.get("binary_sensor.home_mode_guest").state == STATE_ON
    assert hass.states.get("select.home_mode").attributes["overlays"] == ["guest"]
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_overlay_guest"}, blocking=True
    )
    assert hass.states.get("switch.home_mode_overlay_guest").state == STATE_OFF


async def test_auto_switch(hass: HomeAssistant, entry) -> None:
    """The auto switch stores the flag."""
    assert hass.states.get("switch.home_mode_auto").state == STATE_ON
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    assert hass.states.get("switch.home_mode_auto").state == STATE_OFF
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    assert hass.states.get("switch.home_mode_auto").state == STATE_ON


async def test_derived_roles_use_presence_provider(hass: HomeAssistant) -> None:
    """all_home/all_away show unknown until a provider reports, and expose 'selected'."""
    roles = make_entry().options[CONF_ROLES]
    roles = [{**r, "enabled": True} for r in roles]
    fake = FakePresence()
    config_entry = make_entry(options={CONF_ROLES: roles})
    config_entry.add_to_hass(hass)
    with patch("custom_components.home_modes.PresenceTracker", return_value=fake):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    all_home = "binary_sensor.home_mode_all_home"
    all_away = "binary_sensor.home_mode_all_away"
    assert hass.states.get(all_home).state == STATE_UNKNOWN
    assert hass.states.get(all_home).attributes["selected"] is False
    assert "selected" not in hass.states.get("binary_sensor.home_mode_night").attributes

    fake.set(True, False)
    await hass.async_block_till_done()
    assert hass.states.get(all_home).state == STATE_ON
    assert hass.states.get(all_away).state == STATE_OFF

    # Manually selecting a derived role sets the primary; presence truth stays live.
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.home_mode", "option": "All away"},
        blocking=True,
    )
    assert config_entry.runtime_data.coordinator.data.primary == "all_away"
    assert hass.states.get(all_away).attributes["selected"] is True
    assert hass.states.get(all_away).state == STATE_OFF
    assert hass.states.get(all_home).attributes["selected"] is False

    await hass.config_entries.async_unload(config_entry.entry_id)
    assert not fake.listeners


async def test_permission_denied_surfaces_as_error(hass: HomeAssistant, guest_user) -> None:
    """A denied select/switch call raises a translated error."""
    guest = guest_user
    config_entry = make_entry(
        options={CONF_USER_RULES: {guest.id: {"mode": "allow_list", "roles": ["home", "guest"]}}}
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    ctx = Context(user_id=guest.id)

    with pytest.raises(HomeAssistantError, match="not allowed"):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.home_mode", "option": "Night"},
            blocking=True,
            context=ctx,
        )
    assert hass.states.get("select.home_mode").state == "Home"

    # Allowed role works for the guest, denied overlay and auto switch do not.
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.home_mode_overlay_guest"},
        blocking=True,
        context=ctx,
    )
    assert hass.states.get("switch.home_mode_overlay_guest").state == STATE_ON
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.home_mode_overlay_dnd"},
            blocking=True,
            context=ctx,
        )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True, context=ctx
        )
    assert hass.states.get("switch.home_mode_auto").state == STATE_ON
