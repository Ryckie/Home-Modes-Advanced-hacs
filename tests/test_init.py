"""Tests for setup, restore and unload."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.home_modes.const import CONF_ROLES, DOMAIN
from custom_components.home_modes.models import ChangeSource

from .conftest import make_entry


def _roles(disabled: set[str], preset: str = "extended") -> dict:
    entry = make_entry(preset, derived=False)
    return {
        CONF_ROLES: [
            {**r, "enabled": r["enabled"] and r["id"] not in disabled}
            for r in entry.options[CONF_ROLES]
        ]
    }


async def test_setup_and_initial_state(hass: HomeAssistant, entry) -> None:
    """First setup selects home and records a system trigger."""
    assert entry.state is ConfigEntryState.LOADED
    state = entry.runtime_data.coordinator.data
    assert state.primary == "home"
    assert state.previous is None
    assert (state.last_trigger.source, state.last_trigger.rule) == ("system", "initial")


async def test_initial_primary_when_home_disabled(hass: HomeAssistant) -> None:
    """Without home the first enabled primary is used."""
    config_entry = make_entry(options=_roles({"home"}))
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.runtime_data.coordinator.data.primary == "night"


async def test_setup_fails_without_enabled_primary(hass: HomeAssistant) -> None:
    """An entry without any enabled primary cannot start."""
    config_entry = make_entry(options=_roles({"home", "night", "away", "vacation"}))
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_invalid_role_definitions_are_skipped(hass: HomeAssistant, caplog) -> None:
    """Malformed roles are logged and skipped."""
    options = _roles(set())
    options[CONF_ROLES].append({"id": "bogus", "name": "Bogus"})
    options[CONF_ROLES].append({"name": "no id"})
    config_entry = make_entry(options=options)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert "Ignoring invalid role definition" in caplog.text
    assert len(config_entry.runtime_data.coordinator.roles) == 8


async def test_state_is_restored_after_unload(hass: HomeAssistant, entry, hass_storage) -> None:
    """State is flushed on unload and restored on the next setup."""
    runtime = entry.runtime_data
    await runtime.engine.async_set_primary("night", ChangeSource.MANUAL, rule="r")
    await runtime.engine.async_set_overlay("guest", True, ChangeSource.MANUAL)
    await runtime.engine.async_set_auto(False)
    since = runtime.coordinator.data.since

    assert await hass.config_entries.async_unload(entry.entry_id)
    stored = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert stored["primary"] == "night"
    assert stored["overlays"] == ["guest"]

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = entry.runtime_data.coordinator.data
    assert (state.primary, state.previous, state.since) == ("night", "home", since)
    assert state.overlays == ("guest",)
    assert state.auto_enabled is False
    assert (state.last_trigger.source, state.last_trigger.rule) == ("manual", "r")
    assert hass.states.get("select.home_mode").state == "Night"
    assert hass.states.get("switch.home_mode_overlay_guest").state == "on"


async def test_corrupt_storage_starts_fresh(hass: HomeAssistant, hass_storage, caplog) -> None:
    """Corrupt stored state is replaced by the initial state."""
    config_entry = make_entry()
    config_entry.add_to_hass(hass)
    key = f"{DOMAIN}.{config_entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"primary": "night"}}
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert "Stored state is corrupt" in caplog.text
    assert config_entry.runtime_data.coordinator.data.primary == "home"


async def test_restored_removed_role_falls_back(hass: HomeAssistant, hass_storage) -> None:
    """A stored primary that no longer exists falls back via the pipeline."""
    config_entry = make_entry()
    config_entry.add_to_hass(hass)
    key = f"{DOMAIN}.{config_entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "primary": "custom_2",
            "previous": "away",
            "since": (dt_util.utcnow() - timedelta(hours=1)).isoformat(),
        },
    }
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    state = config_entry.runtime_data.coordinator.data
    assert (state.primary, state.previous) == ("away", "custom_2")


async def test_remove_entry_deletes_storage(hass: HomeAssistant, entry, hass_storage) -> None:
    """Removing the entry removes its stored state."""
    key = f"{DOMAIN}.{entry.entry_id}"
    await hass.config_entries.async_unload(entry.entry_id)
    assert key in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    assert key not in hass_storage


async def test_orphaned_entities_are_removed(hass: HomeAssistant, entry) -> None:
    """Entities of roles that are no longer enabled are removed from the registry."""
    registry = er.async_get(hass)
    assert registry.async_get("binary_sensor.home_mode_guest") is not None
    assert registry.async_get("switch.home_mode_overlay_guest") is not None

    hass.config_entries.async_update_entry(entry, options=_roles({"guest", "vacation"}))
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in (
        "binary_sensor.home_mode_guest",
        "switch.home_mode_overlay_guest",
        "binary_sensor.home_mode_vacation",
    ):
        assert registry.async_get(entity_id) is None
        assert hass.states.get(entity_id) is None
    assert registry.async_get("binary_sensor.home_mode_dnd") is not None
    assert hass.states.get("select.home_mode").attributes["options"] == ["Home", "Night", "Away"]


async def test_single_entry_only(hass: HomeAssistant, entry) -> None:
    """The manifest allows one entry per household."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"
