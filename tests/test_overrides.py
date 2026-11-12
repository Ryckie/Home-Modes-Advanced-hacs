"""Source priority, override modes and restart behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_modes.const import EVENT_CHANGED

from .helpers import (
    NIGHT_WINDOW,
    advance,
    call,
    data,
    presence_options,
    primary,
    reload,
    set_state,
    setup_entry,
)

HOME2 = {"person.anna": "home", "person.ben": "home"}
LATE = "2026-11-12 22:30:00+00:00"


async def _leave(hass: HomeAssistant) -> None:
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()


# --- priority: manual vs schedule vs sensor vs presence ------------------------


async def test_schedule_beats_presence_in_one_evaluation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """If schedule and presence would fire together, schedule wins."""
    entry = await setup_entry(
        hass, freezer, {**presence_options(), "night": NIGHT_WINDOW}, start=LATE, states=HOME2
    )
    await _leave(hass)
    since = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
    set_state(entry, since=since, all_away_since=datetime(2026, 11, 12, 22, 0, tzinfo=UTC))
    await entry.runtime_data.rules.async_evaluate()
    assert primary(entry) == "night"
    assert data(entry).last_trigger.source == "schedule"


async def test_sensor_beats_presence_in_one_evaluation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """If a sensor rule and presence would fire together, the sensor wins."""
    options = {
        **presence_options(),
        "night": {"methods": ["sleep_sensors"], "sleep_sensors": ["binary_sensor.bed"]},
    }
    entry = await setup_entry(
        hass, freezer, options, start=LATE, states={**HOME2, "binary_sensor.bed": "off"}
    )
    await _leave(hass)
    set_state(
        entry,
        since=datetime(2026, 11, 12, 20, 0, tzinfo=UTC),
        all_away_since=datetime(2026, 11, 12, 22, 0, tzinfo=UTC),
    )
    hass.states.async_set("binary_sensor.bed", "on")
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    assert data(entry).last_trigger.source == "sensor"


async def test_schedule_beats_sensor_in_one_evaluation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Schedule (rank 2) is evaluated before sensors (rank 3)."""
    options = {
        "night": {
            **NIGHT_WINDOW,
            "methods": ["time_window", "sleep_sensors"],
            "sleep_sensors": ["binary_sensor.bed"],
        },
    }
    entry = await setup_entry(
        hass, freezer, options, start=LATE, states={"binary_sensor.bed": "off"}
    )
    set_state(entry, since=datetime(2026, 11, 12, 20, 0, tzinfo=UTC))
    hass.states.async_set("binary_sensor.bed", "on")
    await hass.async_block_till_done()
    assert data(entry).last_trigger.source == "sensor"  # edge event: sensor group only
    set_state(entry, primary="home", since=datetime(2026, 11, 12, 20, 0, tzinfo=UTC))
    await entry.runtime_data.rules.async_evaluate()
    assert data(entry).last_trigger.source == "schedule"


async def test_manual_beats_schedule_while_override_active(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A timed override ignores the morning schedule; it applies after expiry."""
    options = {
        "morning": {"methods": ["time"], "time": "07:00:00"},
        "override": {"until": "duration", "duration_min": 600},
    }
    entry = await setup_entry(hass, freezer, options, start="2026-11-12 21:59:00+00:00")
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    assert data(entry).override is not None
    await advance(hass, freezer, hours=9, minutes=2)  # 07:01: override active
    assert primary(entry) == "night"
    await advance(hass, freezer, hours=1)  # 08:01: override expired, morning applies
    assert primary(entry) == "home"
    assert data(entry).override is None
    assert data(entry).last_trigger.rule == "morning_time"


# --- override creation (override flag) -----------------------------------------


@pytest.mark.parametrize(
    ("as_user", "flag", "expected"),
    [(True, None, True), (True, False, False), (False, None, False), (False, True, True)],
)
async def test_override_flag_matrix(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_admin_user,
    as_user: bool,
    flag: bool | None,
    expected: bool,
) -> None:
    """override defaults to true with a user and false without one."""
    entry = await setup_entry(hass, freezer)
    payload: dict = {"mode": "night"}
    if flag is not None:
        payload["override"] = flag
    await call(hass, "set_mode", payload, hass_admin_user.id if as_user else None)
    assert (data(entry).override is not None) is expected


# --- the four override.until modes ----------------------------------------------


async def test_override_end_of_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """end_of_day: active until local midnight, then auto-rules apply."""
    entry = await setup_entry(
        hass, freezer, {**presence_options(), "override": {"until": "end_of_day"}}, states=HOME2
    )
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    assert data(entry).override.until == datetime(2026, 11, 13, 0, 0, tzinfo=UTC)
    await _leave(hass)
    await advance(hass, freezer, hours=11)  # 23:00, override active
    assert primary(entry) == "night"
    await advance(hass, freezer, hours=1, minutes=1)  # 00:01, expired
    assert primary(entry) == "away"
    assert data(entry).override is None


async def test_override_next_auto(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """next_auto (default): stays until an auto trigger would fire, which then applies."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    assert data(entry).override is not None
    await advance(hass, freezer, hours=10)  # nothing fires: still active
    assert primary(entry) == "night"
    assert data(entry).override is not None
    await _leave(hass)
    await advance(hass, freezer, minutes=5)  # away rule fires: clears and applies
    assert primary(entry) == "away"
    assert data(entry).override is None
    assert data(entry).last_trigger.rule == "presence_away"


async def test_next_auto_not_cleared_by_rule_that_would_not_fire(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A trigger whose guard fails (night rule while away) does not end the override."""
    entry = await setup_entry(
        hass, freezer, {"night": NIGHT_WINDOW}, start="2026-11-12 21:59:00+00:00"
    )
    await call(hass, "set_mode", {"mode": "away"}, hass_admin_user.id)
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "away"
    assert data(entry).override is not None


async def test_override_duration(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """duration: blocks auto-rules for the duration, then they apply."""
    options = {**presence_options(), "override": {"until": "duration", "duration_min": 30}}
    entry = await setup_entry(hass, freezer, options, states=HOME2)
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    await _leave(hass)
    await advance(hass, freezer, minutes=29)
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "away"


async def test_override_set_auto_mode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """set_auto: lasts until set_auto is called, however long it takes."""
    options = {**presence_options(), "override": {"until": "set_auto"}}
    entry = await setup_entry(hass, freezer, options, states=HOME2)
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    await _leave(hass)
    await advance(hass, freezer, hours=72)
    assert primary(entry) == "night"
    assert data(entry).override is not None
    await call(hass, "set_auto", user_id=hass_admin_user.id)
    assert primary(entry) == "vacation"  # clears the override and re-evaluates now
    assert data(entry).override is None


# --- restart -------------------------------------------------------------------


async def test_restart_during_override(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A running override survives a restart and its expiry timer is re-armed."""
    options = {**presence_options(), "override": {"until": "duration", "duration_min": 60}}
    entry = await setup_entry(hass, freezer, options, states=HOME2)
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    await _leave(hass)
    await advance(hass, freezer, minutes=10)
    await reload(hass, entry)
    assert primary(entry) == "night"
    assert data(entry).override is not None
    await advance(hass, freezer, minutes=40)
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=11)  # 61 minutes after the manual change
    assert primary(entry) == "away"


async def test_restart_with_expired_temporary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A temporary mode that expired while HA was down reverts once at startup."""
    entry = await setup_entry(hass, freezer)
    await call(
        hass, "set_temporary", {"mode": "away", "duration": {"minutes": 10}}, hass_admin_user.id
    )
    assert primary(entry) == "away"
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(minutes=30))
    events = async_capture_events(hass, EVENT_CHANGED)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert [e.data["source"] for e in events] == ["temporary_expiry"]
    assert data(entry).temporary is None
    assert data(entry).override is None


async def test_restart_with_expired_override_and_due_presence(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """Expired override + due away timer: applied once, at startup."""
    options = {**presence_options(), "override": {"until": "duration", "duration_min": 30}}
    entry = await setup_entry(hass, freezer, options, states=HOME2)
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    await _leave(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(hours=2))
    events = async_capture_events(hass, EVENT_CHANGED)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert primary(entry) == "away"
    assert [e.data["rule"] for e in events] == ["presence_away"]
    assert data(entry).override is None


async def test_restart_with_expired_vacation_timer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The vacation clock keeps running across a restart and fires at startup."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    await _leave(hass)
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(hours=25))
    events = async_capture_events(hass, EVENT_CHANGED)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert primary(entry) == "vacation"
    assert [e.data["rule"] for e in events] == ["presence_vacation"]


async def test_restart_rearms_vacation_timer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A vacation timer not yet due is re-armed after a restart."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    await _leave(hass)
    await advance(hass, freezer, hours=2)
    await reload(hass, entry)
    assert primary(entry) == "away"
    await advance(hass, freezer, hours=21)
    assert primary(entry) == "away"
    await advance(hass, freezer, hours=2)
    assert primary(entry) == "vacation"
