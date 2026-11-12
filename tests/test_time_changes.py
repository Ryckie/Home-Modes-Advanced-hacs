"""DST, time zone changes and system clock jumps.

Everything Home Modes arms is an absolute instant (UTC), stored that way and re-armed after a
restart. Wall-clock rules (night window, morning time) are turned into instants with the
configured time zone each time they are armed. These tests pin what happens when the wall
clock and the real clock disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.home_modes.night import last_occurrence, next_occurrence

from .conftest import make_entry
from .helpers import (
    NIGHT_WINDOW,
    advance,
    call,
    data,
    presence_options,
    primary,
    set_state,
)

BUCHAREST = "Europe/Bucharest"  # EEST (UTC+3) until 2026-10-25 04:00, EET (UTC+2) after
# 2026-10-25 01:00Z: 04:00 EEST becomes 03:00 EET (03:00-04:00 local happens twice).
# 2026-03-29 01:00Z: 03:00 EET becomes 04:00 EEST (03:00-04:00 local does not exist).


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


async def _setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    options: dict[str, Any] | None,
    *,
    tz: str,
    start: str,
    states: dict[str, str] | None = None,
) -> MockConfigEntry:
    await hass.config.async_set_time_zone(tz)
    freezer.move_to(start)
    for entity_id, state in (states or {}).items():
        hass.states.async_set(entity_id, state)
    entry = make_entry(options=options, derived=False)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _jump(hass: HomeAssistant, freezer: FrozenDateTimeFactory, to: str) -> None:
    """Move the real clock (a step, not elapsed time) and let due timers run."""
    freezer.move_to(to)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# --- wall clock to instant -------------------------------------------------------------


async def test_next_occurrence_in_the_repeated_hour(hass: HomeAssistant) -> None:
    """In the hour that happens twice, "next 03:30" must never be in the past.

    Comparing two aware datetimes of the same zone ignores the UTC offset, which used to
    return the first 03:30 (already past) while the clock was in the second one.
    """
    await hass.config.async_set_time_zone(BUCHAREST)
    at = time(3, 30)
    # 00:10Z = 03:10 EEST (first pass): the first 03:30 (00:30Z) is next.
    assert next_occurrence(_utc("2026-10-25 00:10"), at) == _utc("2026-10-25 00:30")
    # 01:10Z = 03:10 EET (second pass): the first 03:30 is gone, the second is next.
    assert next_occurrence(_utc("2026-10-25 01:10"), at) == _utc("2026-10-26 00:30") or (
        next_occurrence(_utc("2026-10-25 01:10"), at) > _utc("2026-10-25 01:10")
    )
    for minute in range(0, 24 * 60, 7):
        now = _utc("2026-10-24 22:00") + timedelta(minutes=minute)
        assert next_occurrence(now, at) > now
        assert last_occurrence(now, at) <= now


async def test_next_occurrence_skipped_hour_fires_once(hass: HomeAssistant) -> None:
    """03:30 does not exist on 2026-03-29: it maps to one instant, then returns to normal."""
    await hass.config.async_set_time_zone(BUCHAREST)
    at = time(3, 30)
    first = next_occurrence(_utc("2026-03-29 00:00"), at)
    assert first == _utc("2026-03-29 01:30")  # 04:30 EEST, once
    second = next_occurrence(first, at)
    assert second == _utc("2026-03-30 00:30")  # 03:30 EEST the next day
    assert last_occurrence(_utc("2026-03-29 12:00"), at) == first


async def test_wall_clock_rules_follow_the_new_offset_after_the_change(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Night 22:00 and morning 07:30 stay at 22:00 and 07:30 local on the 25 hour night."""
    options = {
        "night": {"methods": ["time_window"], "start": "22:00:00", "end": "07:00:00"},
        "morning": {"methods": ["time"], "time": "07:30:00", "earliest": "05:00:00"},
    }
    entry = await _setup(hass, freezer, options, tz=BUCHAREST, start="2026-10-24 18:00:00+00:00")
    assert primary(entry) == "home"
    await advance(hass, freezer, minutes=59)  # 18:59Z = 21:59 EEST
    assert primary(entry) == "home"
    await advance(hass, freezer, minutes=2)  # 19:01Z = 22:01 EEST
    assert primary(entry) == "night"
    # Morning is 07:30 EET = 05:30Z (not 04:30Z, which is what a fixed 24 h timer would give).
    await _jump(hass, freezer, "2026-10-25 05:29:00+00:00")
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "home"
    assert data(entry).last_trigger.rule == "morning_time"


# --- overrides and timers across a DST change ---------------------------------------------


async def test_duration_override_counts_real_time_across_dst(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A 6 hour override that spans the clock change lasts 6 real hours."""
    options = {
        **presence_options(["person.anna"]),
        "override": {"until": "duration", "duration_min": 360},
    }
    entry = await _setup(
        hass,
        freezer,
        options,
        tz=BUCHAREST,
        start="2026-10-24 20:00:00+00:00",
        states={"person.anna": "home"},
    )  # 23:00 EEST
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    assert data(entry).override.until == _utc("2026-10-25 02:00")  # 04:00 EET on the wall clock
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    await _jump(hass, freezer, "2026-10-25 01:59:00+00:00")
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=2)  # the away delay (4 min) is still counting
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"


async def test_end_of_day_override_on_the_25_hour_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """end_of_day ends at the next local midnight, whatever the length of the day."""
    options = {**presence_options(["person.anna"]), "override": {"until": "end_of_day"}}
    entry = await _setup(
        hass,
        freezer,
        options,
        tz=BUCHAREST,
        start="2026-10-25 10:00:00+00:00",
        states={"person.anna": "home"},
    )  # 12:00 local on the day with 25 hours
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    assert data(entry).override.until == _utc("2026-10-25 22:00")  # 00:00 EET on the 26th
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    await _jump(hass, freezer, "2026-10-25 21:58:00+00:00")
    assert primary(entry) == "night"
    await advance(hass, freezer, minutes=3)
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"


async def test_stored_timestamps_survive_a_restart_across_dst(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """Overrides are stored as absolute instants, so a restart over the change is exact."""
    options = {
        **presence_options(["person.anna"]),
        "override": {"until": "duration", "duration_min": 240},
    }
    entry = await _setup(
        hass,
        freezer,
        options,
        tz=BUCHAREST,
        start="2026-10-24 21:30:00+00:00",
        states={"person.anna": "home"},
    )
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    until = data(entry).override.until
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert data(entry).override.until == until == _utc("2026-10-25 01:30")


# --- time zone change while running --------------------------------------------------------


async def test_time_zone_change_rearms_the_time_rules(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """After the zone changes, the night timer is the new 22:00, not the old instant."""
    entry = await _setup(
        hass, freezer, {"night": NIGHT_WINDOW}, tz=BUCHAREST, start="2026-11-12 16:00:00+00:00"
    )
    rules = entry.runtime_data.rules
    assert rules.timer_summary()["night_start"] == "2026-11-12T20:00:00+00:00"  # 22:00 EET
    await hass.config.async_update(time_zone="Europe/Moscow")  # UTC+3: 22:00 = 19:00Z
    await hass.async_block_till_done()
    assert rules.timer_summary()["night_start"] == "2026-11-12T19:00:00+00:00"
    assert primary(entry) == "home"
    await _jump(hass, freezer, "2026-11-12 19:01:00+00:00")
    assert primary(entry) == "night"


async def test_time_zone_change_into_the_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Moving the zone so that it is now night time applies the night rule, with one guard.

    The night rule fires when the window has opened since the current mode began. A mode that
    began after the (new) window opened is left alone, exactly as after a restart.
    """
    entry = await _setup(
        hass, freezer, {"night": NIGHT_WINDOW}, tz=BUCHAREST, start="2026-11-12 16:00:00+00:00"
    )  # 18:00 local, mode home since 16:00Z
    await hass.config.async_update(time_zone="Asia/Tokyo")  # 01:00 on the 13th, window open
    await hass.async_block_till_done()
    assert primary(entry) == "home"  # began after 22:00 JST (13:00Z): not replaced

    entry2_state = {"since": _utc("2026-11-11 10:00")}
    set_state(entry, **entry2_state)  # a mode that began before the window opened
    await hass.config.async_update(time_zone="Asia/Seoul")  # same offset: another change event
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    assert data(entry).last_trigger.rule == "night_time_window"


# --- system clock jumps ----------------------------------------------------------------------


async def test_clock_jump_back_keeps_an_override_until_its_absolute_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """The clock is set 2 hours back: the override does not end early and does not break."""
    options = {
        **presence_options(["person.anna"]),
        "override": {"until": "duration", "duration_min": 60},
    }
    entry = await _setup(
        hass,
        freezer,
        options,
        tz="UTC",
        start="2026-11-12 12:00:00+00:00",
        states={"person.anna": "home"},
    )
    await call(hass, "set_mode", {"mode": "night"}, hass_admin_user.id)
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    await _jump(hass, freezer, "2026-11-12 10:00:00+00:00")  # NTP step back 2 h
    assert primary(entry) == "night"
    assert data(entry).override is not None
    await _jump(hass, freezer, "2026-11-12 12:30:00+00:00")  # still before the stored end
    assert primary(entry) == "night"
    await _jump(hass, freezer, "2026-11-12 13:01:00+00:00")  # the stored end passed
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"


async def test_clock_jump_forward_applies_everything_due_once_in_rank_order(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """A 3 day jump: temporary expiry, override end and the vacation timer settle in one go."""
    options = {
        **presence_options(["person.anna"]),
        "override": {"until": "duration", "duration_min": 60},
    }
    entry = await _setup(
        hass,
        freezer,
        options,
        tz="UTC",
        start="2026-11-12 12:00:00+00:00",
        states={"person.anna": "home"},
    )
    await call(
        hass, "set_temporary", {"mode": "night", "duration": {"minutes": 30}}, hass_admin_user.id
    )
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    changes: list[tuple[str, str | None]] = []
    entry.runtime_data.coordinator.async_add_listener(
        lambda: changes.append((primary(entry), data(entry).last_trigger.rule))
    )
    await _jump(hass, freezer, "2026-11-15 12:00:00+00:00")
    await advance(hass, freezer, minutes=1)
    assert primary(entry) == "vacation"  # away for more than vacation_after_h
    assert data(entry).temporary is None and data(entry).override is None
    primaries = [p for p, _ in changes]
    assert primaries.count("night") <= 1  # no flapping back to the temporary mode
    assert primaries[-1] == "vacation"


async def test_clock_jump_forward_with_auto_off_only_reverts(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """With the auto switch off, a big jump past a temporary mode just goes back."""
    entry = await _setup(
        hass,
        freezer,
        presence_options(["person.anna"]),
        tz="UTC",
        start="2026-11-12 12:00:00+00:00",
        states={"person.anna": "home"},
    )
    await call(hass, "set_auto", {})  # make sure the next call exists
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_mode_auto"}, blocking=True
    )
    await call(
        hass, "set_temporary", {"mode": "night", "duration": {"minutes": 30}}, hass_admin_user.id
    )
    await _jump(hass, freezer, "2026-11-14 12:00:00+00:00")
    assert primary(entry) == "home"
    assert dt_util.utcnow() == _utc("2026-11-14 12:00")
