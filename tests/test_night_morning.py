"""Night and morning methods."""

from __future__ import annotations

from datetime import UTC

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.home_modes.night import in_window, last_occurrence, next_occurrence

from .helpers import NIGHT_WINDOW, advance, call, data, primary, setup_entry

EVENING = "2026-11-12 21:59:00+00:00"


async def test_time_window_night_and_morning_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Schedule rules: night at window start, home at the morning time."""
    options = {
        "night": {**NIGHT_WINDOW, "end": "08:00:00"},
        "morning": {"methods": ["time"], "time": "07:00:00"},
    }
    entry = await setup_entry(hass, freezer, options, start=EVENING)
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "night"
    assert (data(entry).last_trigger.source, data(entry).last_trigger.rule) == (
        "schedule",
        "night_time_window",
    )
    await advance(hass, freezer, hours=9)  # 07:01, still inside the 22:00-08:00 window
    assert primary(entry) == "home"
    assert data(entry).last_trigger.rule == "morning_time"
    # No flip-flop: inside the window the night rule does not fire again.
    await advance(hass, freezer, minutes=30)
    assert primary(entry) == "home"


async def test_night_only_from_home_like_modes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Night rules never leave away or vacation."""
    entry = await setup_entry(hass, freezer, {"night": NIGHT_WINDOW}, start=EVENING)
    await call(hass, "set_mode", {"mode": "away"})
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "away"


async def test_sleep_sensor(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A sleep sensor turning on sets night (sensor rank)."""
    options = {
        "night": {"methods": ["sleep_sensors"], "sleep_sensors": ["binary_sensor.bed"]},
    }
    entry = await setup_entry(hass, freezer, options, states={"binary_sensor.bed": "off"})
    hass.states.async_set("binary_sensor.bed", "on")
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    assert (data(entry).last_trigger.source, data(entry).last_trigger.rule) == (
        "sensor",
        "night_sleep_sensor",
    )


async def test_phone_charging_only_inside_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Phone charging counts only inside the night window."""
    options = {
        "night": {
            "methods": ["phone_charging"],
            "start": "22:00:00",
            "end": "06:00:00",
            "charging_sensors": ["binary_sensor.charging", "sensor.phone_state"],
        },
    }
    entry = await setup_entry(
        hass,
        freezer,
        options,
        states={"binary_sensor.charging": "off", "sensor.phone_state": "Discharging"},
    )
    hass.states.async_set("binary_sensor.charging", "on")  # noon: outside the window
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    await advance(hass, freezer, hours=11)  # 23:00 inside the window
    hass.states.async_set("sensor.phone_state", "charging")
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    assert data(entry).last_trigger.rule == "night_phone_charging"


async def test_morning_motion_guarded_by_earliest(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Motion ends the night only from the earliest time (and not in the evening)."""
    options = {
        "night": NIGHT_WINDOW,
        "morning": {
            "methods": ["motion"],
            "earliest": "05:00:00",
            "motion_sensors": ["binary_sensor.hall"],
        },
    }
    entry = await setup_entry(
        hass,
        freezer,
        options,
        start="2026-11-12 23:00:00+00:00",
        states={"binary_sensor.hall": "off"},
    )
    await call(hass, "set_mode", {"mode": "night"})
    hass.states.async_set("binary_sensor.hall", "on")  # 23:00: evening, ignored
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    await advance(hass, freezer, hours=3)  # 02:00 before earliest
    hass.states.async_set("binary_sensor.hall", "off")
    hass.states.async_set("binary_sensor.hall", "on")
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    await advance(hass, freezer, hours=3, minutes=30)  # 05:30
    hass.states.async_set("binary_sensor.hall", "off")
    hass.states.async_set("binary_sensor.hall", "on")
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert data(entry).last_trigger.rule == "morning_motion"


async def test_morning_alarm_sensor(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The next-alarm timestamp ends the night when it is reached."""
    options = {"morning": {"methods": ["alarm"], "alarm_sensors": ["sensor.phone_alarm"]}}
    entry = await setup_entry(hass, freezer, options, states={"sensor.phone_alarm": "unknown"})
    await call(hass, "set_mode", {"mode": "night"})
    hass.states.async_set("sensor.phone_alarm", "2026-11-12T13:30:00+00:00")
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    await advance(hass, freezer, hours=1, minutes=29)
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "home"
    assert (data(entry).last_trigger.source, data(entry).last_trigger.rule) == (
        "sensor",
        "morning_alarm",
    )


async def test_manual_methods_do_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With only the manual method selected no auto-rule runs."""
    options = {"night": {"methods": ["manual"]}, "morning": {"methods": ["manual"]}}
    entry = await setup_entry(hass, freezer, options, start=EVENING)
    await advance(hass, freezer, hours=12)
    assert primary(entry) == "home"
    await call(hass, "set_mode", {"mode": "night"})
    await advance(hass, freezer, hours=12)
    assert primary(entry) == "night"


async def test_disabled_night_role_is_skipped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Auto-rules never target a disabled role."""
    from .helpers import roles_without

    options = {"night": NIGHT_WINDOW, "roles": roles_without("night")}
    entry = await setup_entry(hass, freezer, options, start=EVENING)
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "home"
    assert hass.states.get("sensor.home_mode_trigger_reason").attributes["rule"] == "initial"


async def test_time_helpers(hass: HomeAssistant) -> None:
    """Window and occurrence helpers handle midnight."""
    from datetime import datetime, time

    await hass.config.async_set_time_zone("UTC")

    assert in_window(time(23), time(22), time(6))
    assert in_window(time(5), time(22), time(6))
    assert not in_window(time(12), time(22), time(6))
    assert in_window(time(9), time(8), time(17))
    assert not in_window(time(9), time(9), time(9))
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    assert last_occurrence(now, time(7)) == datetime(2026, 11, 12, 7, 0, tzinfo=UTC)
    assert last_occurrence(now, time(22)) == datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    assert next_occurrence(now, time(22)) == datetime(2026, 11, 12, 22, 0, tzinfo=UTC)
    assert next_occurrence(now, time(7)) == datetime(2026, 11, 13, 7, 0, tzinfo=UTC)
