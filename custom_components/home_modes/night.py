"""Night and morning rules: time helpers and candidate generation."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .const import (
    MORNING_ALARM,
    MORNING_MOTION,
    MORNING_TIME,
    NIGHT_PHONE_CHARGING,
    NIGHT_SLEEP_SENSORS,
    NIGHT_TIME_WINDOW,
    ROLE_HOME,
    ROLE_NIGHT,
)
from .models import AutoCandidate, ChangeSource, HomeModesState, RoleType, role_type_from_id
from .settings import AutoSettings

# Trigger groups: which kind of event caused an evaluation.
GROUP_TIME = "time"
GROUP_SLEEP = "sleep"
GROUP_CHARGING = "charging"
GROUP_MOTION = "motion"
GROUP_ALARM = "alarm"
GROUP_PRESENCE = "presence"

RULE_NIGHT_TIME_WINDOW = "night_time_window"
RULE_NIGHT_SLEEP_SENSOR = "night_sleep_sensor"
RULE_NIGHT_PHONE_CHARGING = "night_phone_charging"
RULE_MORNING_TIME = "morning_time"
RULE_MORNING_MOTION = "morning_motion"
RULE_MORNING_ALARM = "morning_alarm"

# Primary modes a night rule may leave. Away, vacation and all_away never go to night.
_NIGHT_ENTRY_TYPES = frozenset({RoleType.HOME, RoleType.ALL_HOME, RoleType.CUSTOM})
CHARGING_STATES = frozenset({"on", "charging"})


def in_window(value: time, start: time, end: time) -> bool:
    """Return True if a time of day is inside the window (may span midnight)."""
    if start == end:
        return False
    if start < end:
        return start <= value < end
    return value >= start or value < end


def _local_at(day: date, at: time) -> datetime:
    """Return the instant (UTC) of a local wall-clock time on a local day.

    A time that does not exist (spring forward) maps to the same instant the clock reading
    would have with the offset before the change, i.e. it fires once, one hour later on the
    wall clock. A time that exists twice (fall back) maps to its first occurrence.
    """
    local = datetime.combine(day, at.replace(microsecond=0), tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(local)


def last_occurrence(now: datetime, at: time) -> datetime:
    """Return the most recent local occurrence of a time of day at or before now.

    Instants are compared in UTC: comparing two aware datetimes that share a time zone
    ignores the UTC offset, which is wrong inside the repeated hour of a DST change.
    """
    today = dt_util.as_local(now).date()
    candidate = _local_at(today, at)
    if candidate > dt_util.as_utc(now):
        candidate = _local_at(today - timedelta(days=1), at)
    return candidate


def next_occurrence(now: datetime, at: time) -> datetime:
    """Return the next local occurrence of a time of day strictly after now (UTC compare)."""
    today = dt_util.as_local(now).date()
    candidate = _local_at(today, at)
    if candidate <= dt_util.as_utc(now):
        candidate = _local_at(today + timedelta(days=1), at)
    return candidate


def _can_enter_night(primary: str) -> bool:
    return role_type_from_id(primary) in _NIGHT_ENTRY_TYPES


def is_on(state: State | None) -> bool:
    return state is not None and state.state == STATE_ON


def is_charging(state: State | None) -> bool:
    return state is not None and state.state.lower() in CHARGING_STATES


def alarm_time(state: State | None) -> datetime | None:
    """Return the next alarm timestamp of an alarm sensor, if it has a valid one."""
    if state is None:
        return None
    return dt_util.parse_datetime(state.state)


def morning_motion_allowed(settings: AutoSettings, now: datetime) -> bool:
    """Return True if a motion event counts as morning at this time of day."""
    local = dt_util.as_local(now).time()
    earliest, start = settings.morning.earliest, settings.night.start
    if local < earliest:
        return False
    return not (start > earliest and local >= start)


def night_candidates(
    hass: HomeAssistant,
    settings: AutoSettings,
    state: HomeModesState,
    now: datetime,
    groups: frozenset[str] | None,
) -> list[AutoCandidate]:
    """Return night entry candidates in rank order (schedule, then sensors)."""
    if not _can_enter_night(state.primary):
        return []
    night = settings.night
    found: list[AutoCandidate] = []

    def wanted(group: str) -> bool:
        return groups is None or group in groups

    if NIGHT_TIME_WINDOW in night.methods and wanted(GROUP_TIME):
        local = dt_util.as_local(now).time()
        if in_window(local, night.start, night.end) and state.since < last_occurrence(
            now, night.start
        ):
            found.append(AutoCandidate(ChangeSource.SCHEDULE, RULE_NIGHT_TIME_WINDOW, ROLE_NIGHT))
    if NIGHT_SLEEP_SENSORS in night.methods and wanted(GROUP_SLEEP):
        for entity_id in night.sleep_sensors:
            sensor = hass.states.get(entity_id)
            if is_on(sensor) and sensor is not None and sensor.last_changed >= state.since:
                found.append(
                    AutoCandidate(ChangeSource.SENSOR, RULE_NIGHT_SLEEP_SENSOR, ROLE_NIGHT)
                )
                break
    if NIGHT_PHONE_CHARGING in night.methods and wanted(GROUP_CHARGING):
        local = dt_util.as_local(now).time()
        if in_window(local, night.start, night.end):
            for entity_id in night.charging_sensors:
                sensor = hass.states.get(entity_id)
                if (
                    is_charging(sensor)
                    and sensor is not None
                    and sensor.last_changed >= state.since
                ):
                    found.append(
                        AutoCandidate(ChangeSource.SENSOR, RULE_NIGHT_PHONE_CHARGING, ROLE_NIGHT)
                    )
                    break
    return found


def morning_candidates(
    hass: HomeAssistant,
    settings: AutoSettings,
    state: HomeModesState,
    now: datetime,
    groups: frozenset[str] | None,
    *,
    motion_event: bool = False,
) -> list[AutoCandidate]:
    """Return morning (night exit) candidates in rank order."""
    if state.primary != ROLE_NIGHT:
        return []
    morning = settings.morning
    found: list[AutoCandidate] = []

    def wanted(group: str) -> bool:
        return groups is None or group in groups

    if (
        MORNING_TIME in morning.methods
        and wanted(GROUP_TIME)
        and state.since < last_occurrence(now, morning.at) <= now
    ):
        found.append(AutoCandidate(ChangeSource.SCHEDULE, RULE_MORNING_TIME, ROLE_HOME))
    if MORNING_ALARM in morning.methods and wanted(GROUP_ALARM):
        for entity_id in morning.alarm_sensors:
            ts = alarm_time(hass.states.get(entity_id))
            if ts is not None and state.since < ts <= now:
                found.append(AutoCandidate(ChangeSource.SENSOR, RULE_MORNING_ALARM, ROLE_HOME))
                break
    # Motion is edge-only: only evaluated when a motion sensor just turned on.
    if (
        MORNING_MOTION in morning.methods
        and motion_event
        and wanted(GROUP_MOTION)
        and morning_motion_allowed(settings, now)
    ):
        found.append(AutoCandidate(ChangeSource.SENSOR, RULE_MORNING_MOTION, ROLE_HOME))
    return found
