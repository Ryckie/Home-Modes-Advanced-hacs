"""Options flow screens added in Step 3, settings parsing and Step 2 follow-ups."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from custom_components.home_modes.models import (
    ChangeSource,
    HomeModesState,
    Override,
    OverrideMode,
    Temporary,
)
from custom_components.home_modes.settings import parse_settings

from .helpers import call, data, primary, setup_entry


async def _step(hass: HomeAssistant, flow_id: str, step: str, payload: dict | None = None):
    result = await hass.config_entries.options.async_configure(flow_id, {"next_step_id": step})
    if payload is None:
        return result
    return await hass.config_entries.options.async_configure(flow_id, payload)


async def test_presence_night_morning_override_screens(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Every new screen stores its values and parses back into the settings."""
    entry = await setup_entry(hass, freezer)
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]

    result = await _step(
        hass,
        flow_id,
        "presence",
        {"persons": ["person.anna"], "away_delay_min": 7, "vacation_after_h": 48},
    )
    assert result["type"] is FlowResultType.MENU
    result = await _step(
        hass,
        flow_id,
        "night",
        {
            "methods": ["time_window", "sleep_sensors", "phone_charging"],
            "start": "23:00:00",
            "end": "05:00:00",
            "sleep_sensors": ["binary_sensor.bed"],
            "charging_sensors": ["sensor.phone"],
        },
    )
    assert result["type"] is FlowResultType.MENU
    result = await _step(
        hass,
        flow_id,
        "morning",
        {
            "methods": ["time", "motion", "alarm"],
            "time": "06:30:00",
            "earliest": "05:30:00",
            "motion_sensors": ["binary_sensor.hall"],
            "alarm_sensors": ["sensor.alarm"],
        },
    )
    assert result["type"] is FlowResultType.MENU
    result = await _step(hass, flow_id, "override", {"until": "duration", "duration_min": 45})
    assert result["type"] is FlowResultType.MENU
    await _step(hass, flow_id, "save")
    await hass.async_block_till_done()

    settings = parse_settings(entry.options)
    assert settings.persons == ("person.anna",)
    assert settings.away_delay == timedelta(minutes=7)
    assert settings.vacation_after == timedelta(hours=48)
    assert settings.night.start.hour == 23
    assert settings.night.methods == {"time_window", "sleep_sensors", "phone_charging"}
    assert settings.morning.alarm_sensors == ("sensor.alarm",)
    assert (settings.override.until, settings.override.duration) == (
        "duration",
        timedelta(minutes=45),
    )
    assert entry.runtime_data.coordinator.settings == settings  # reloaded with new options
    assert len(entry.options["roles"]) == 8  # roles untouched


async def test_night_and_morning_validation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Methods need their sensors; the window must not be empty."""
    entry = await setup_entry(hass, freezer)
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    result = await _step(
        hass,
        flow_id,
        "night",
        {
            "methods": ["sleep_sensors", "phone_charging"],
            "start": "22:00:00",
            "end": "22:00:00",
        },
    )
    assert result["errors"] == {
        "sleep_sensors": "sensors_required",
        "charging_sensors": "sensors_required",
        "end": "window_empty",
    }
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    result = await _step(
        hass,
        flow_id,
        "morning",
        {"methods": ["motion", "alarm"], "time": "07:00:00", "earliest": "05:00:00"},
    )
    assert result["errors"] == {
        "motion_sensors": "sensors_required",
        "alarm_sensors": "sensors_required",
    }


async def test_user_rules_step_enforces_guest(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user, hass_admin_user
) -> None:
    """A guest rule saved in the options flow is enforced server-side."""
    entry = await setup_entry(hass, freezer)
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    result = await _step(hass, flow_id, "user_rules")
    users = result["data_schema"].schema["user"].config["options"]
    assert guest_user.id in {u["value"] for u in users}
    # Admins are always unrestricted, so they are not offered.
    assert hass_admin_user.id not in {u["value"] for u in users}
    result = await hass.config_entries.options.async_configure(flow_id, {"user": guest_user.id})
    assert result["step_id"] == "user_rule_edit"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"mode": "allow_list", "roles": ["home", "away"]}
    )
    assert result["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    # Saved on submit, before the options are closed.
    assert entry.options["user_rules"][guest_user.id] == {
        "mode": "allow_list",
        "roles": ["home", "away"],
    }

    await call(hass, "set_mode", {"mode": "away"}, guest_user.id)
    assert primary(entry) == "away"
    with pytest.raises(HomeAssistantError, match="not allowed"):
        await call(hass, "set_mode", {"mode": "night"}, guest_user.id)
    assert primary(entry) == "away"

    # Switching the rule back to unrestricted drops the stored roles.
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    result = await _step(hass, flow_id, "user_rules", {"user": guest_user.id})
    # The edit screen starts from the stored rule.
    schema = {str(k): k for k in result["data_schema"].schema}
    assert schema["mode"].default() == "allow_list"
    assert schema["roles"].default() == ["home", "away"]
    await hass.config_entries.options.async_configure(
        flow_id, {"mode": "unrestricted", "roles": ["home"]}
    )
    await _step(hass, flow_id, "save")
    await hass.async_block_till_done()
    assert entry.options["user_rules"][guest_user.id] == {"mode": "unrestricted", "roles": []}
    await call(hass, "set_mode", {"mode": "night"}, guest_user.id)
    assert primary(entry) == "night"


def test_settings_defaults_and_invalid_values() -> None:
    """Missing or invalid options fall back to defaults."""
    settings = parse_settings({})
    assert settings.persons == ()
    assert settings.away_delay == timedelta(minutes=4)
    assert settings.vacation_after == timedelta(hours=24)
    assert settings.override.until == "next_auto"
    assert settings.night.methods == frozenset()

    bad = parse_settings(
        {
            "away_delay_min": "soon",
            "night": {"methods": ["time_window", "bogus"], "start": "nonsense"},
            "override": {"until": "whenever"},
            "persons": "person.anna",
        }
    )
    assert bad.away_delay == timedelta(minutes=4)
    assert bad.night.methods == {"time_window"}
    assert bad.night.start.hour == 22
    assert bad.override.until == "next_auto"
    assert bad.persons == ()


def test_state_roundtrip_with_step3_fields() -> None:
    """Override mode, temporary and all_away_since are stored as absolute timestamps."""
    from homeassistant.util import dt as dt_util

    now = dt_util.utcnow()
    state = HomeModesState(
        primary="away",
        since=now,
        override=Override("manual", None, OverrideMode.NEXT_AUTO),
        temporary=Temporary("home", now + timedelta(minutes=5)),
        all_away_since=now,
    )
    restored = HomeModesState.from_dict(state.to_dict())
    assert restored == state
    legacy = {"primary": "home", "since": now.isoformat(), "override": {"set_by": "manual"}}
    assert HomeModesState.from_dict(legacy).override == Override("manual")


# --- Step 2 follow-ups ------------------------------------------------------------


async def test_role_and_mode_id_attributes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Select and binary sensors expose the role type and the mode id."""
    from custom_components.home_modes.config_flow import HomeModesConfigFlow  # noqa: F401

    options = {"roles": _with_custom()}
    entry = await setup_entry(hass, freezer, options)
    await call(hass, "set_mode", {"mode": "custom_1"})
    select = hass.states.get("select.home_mode")
    assert select.state == "Movie"
    assert (select.attributes["role"], select.attributes["mode_id"]) == ("custom", "custom_1")
    sensor = hass.states.get("binary_sensor.home_mode_custom_1")
    assert (sensor.attributes["role"], sensor.attributes["mode_id"]) == ("custom", "custom_1")
    assert sensor.state == "on"
    night = hass.states.get("binary_sensor.home_mode_night")
    assert (night.attributes["role"], night.attributes["mode_id"]) == ("night", "night")
    assert primary(entry) == "custom_1"


def _with_custom() -> list[dict]:
    from custom_components.home_modes.config_flow import build_preset_roles

    roles = build_preset_roles("extended")
    roles.insert(4, {"id": "custom_1", "name": "Movie", "enabled": True})
    return roles


async def test_extended_preset_enables_derived_roles(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Extended enables all_home/all_away; Simple keeps them disabled."""
    from custom_components.home_modes.config_flow import build_preset_roles

    simple = {r["id"]: r["enabled"] for r in build_preset_roles("simple")}
    extended = {r["id"]: r["enabled"] for r in build_preset_roles("extended")}
    assert not simple["all_home"] and not simple["all_away"]
    assert extended["all_home"] and extended["all_away"]
    await setup_entry(hass, freezer, derived=True)
    assert hass.states.get("binary_sensor.home_mode_all_home") is not None


async def test_reconcile_never_falls_back_to_derived(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A derived previous mode is skipped when the active role is disabled."""
    entry = await setup_entry(hass, freezer, derived=True)
    engine = entry.runtime_data.engine
    await engine.async_set_primary("all_home", ChangeSource.MANUAL)
    await engine.async_set_primary("night", ChangeSource.MANUAL)
    assert data(entry).previous == "all_home"
    coordinator = entry.runtime_data.coordinator
    from custom_components.home_modes.models import Role

    coordinator.roles = tuple(
        Role(r.id, r.name, r.enabled and r.id != "night") for r in coordinator.roles
    )
    await engine.async_reconcile()
    assert primary(entry) == "home"  # first enabled kind-primary, not all_home
    assert data(entry).last_trigger.rule == "role_disabled"
