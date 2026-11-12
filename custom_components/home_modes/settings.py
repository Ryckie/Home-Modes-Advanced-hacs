"""Parsed automation settings (stored in the config entry options)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_AWAY_DELAY_MIN,
    CONF_MORNING,
    CONF_NIGHT,
    CONF_OVERRIDE,
    CONF_PERSONS,
    CONF_VACATION_AFTER_H,
    DEFAULT_AWAY_DELAY_MIN,
    DEFAULT_MORNING_EARLIEST,
    DEFAULT_MORNING_TIME,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_OVERRIDE_DURATION_MIN,
    DEFAULT_OVERRIDE_UNTIL,
    DEFAULT_VACATION_AFTER_H,
    MORNING_METHODS,
    NIGHT_METHODS,
    UNTIL_MODES,
)

# Option keys inside the night / morning / override dictionaries.
KEY_METHODS = "methods"
KEY_START = "start"
KEY_END = "end"
KEY_SLEEP_SENSORS = "sleep_sensors"
KEY_CHARGING_SENSORS = "charging_sensors"
KEY_TIME = "time"
KEY_EARLIEST = "earliest"
KEY_MOTION_SENSORS = "motion_sensors"
KEY_ALARM_SENSORS = "alarm_sensors"
KEY_UNTIL = "until"
KEY_DURATION_MIN = "duration_min"


def _time(raw: Any, default: str) -> time:
    parsed = dt_util.parse_time(str(raw)) if raw else None
    return parsed or dt_util.parse_time(default) or time(0, 0)


def _strings(raw: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in raw) if isinstance(raw, list | tuple) else ()


def _methods(raw: Any, allowed: tuple[str, ...]) -> frozenset[str]:
    return frozenset(m for m in _strings(raw) if m in allowed)


@dataclass(frozen=True, slots=True)
class NightSettings:
    """Night entry methods."""

    methods: frozenset[str] = frozenset()
    start: time = time(22, 0)
    end: time = time(6, 0)
    sleep_sensors: tuple[str, ...] = ()
    charging_sensors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MorningSettings:
    """Morning (night exit) methods."""

    methods: frozenset[str] = frozenset()
    at: time = time(7, 0)
    earliest: time = time(5, 0)
    motion_sensors: tuple[str, ...] = ()
    alarm_sensors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OverrideSettings:
    """How long a manual override lasts."""

    until: str = DEFAULT_OVERRIDE_UNTIL
    duration: timedelta = timedelta(minutes=DEFAULT_OVERRIDE_DURATION_MIN)


@dataclass(frozen=True, slots=True)
class AutoSettings:
    """All automation settings."""

    persons: tuple[str, ...] = ()
    away_delay: timedelta = timedelta(minutes=DEFAULT_AWAY_DELAY_MIN)
    vacation_after: timedelta = timedelta(hours=DEFAULT_VACATION_AFTER_H)
    night: NightSettings = field(default_factory=NightSettings)
    morning: MorningSettings = field(default_factory=MorningSettings)
    override: OverrideSettings = field(default_factory=OverrideSettings)


def parse_settings(options: Mapping[str, Any]) -> AutoSettings:
    """Parse the options, falling back to defaults for missing or invalid values."""
    night = options.get(CONF_NIGHT) or {}
    morning = options.get(CONF_MORNING) or {}
    override = options.get(CONF_OVERRIDE) or {}
    until = override.get(KEY_UNTIL, DEFAULT_OVERRIDE_UNTIL)
    try:
        away_delay = timedelta(minutes=float(options.get(CONF_AWAY_DELAY_MIN, 4)))
        vacation_after = timedelta(hours=float(options.get(CONF_VACATION_AFTER_H, 24)))
        duration = timedelta(
            minutes=float(override.get(KEY_DURATION_MIN, DEFAULT_OVERRIDE_DURATION_MIN))
        )
    except TypeError, ValueError:
        away_delay = timedelta(minutes=DEFAULT_AWAY_DELAY_MIN)
        vacation_after = timedelta(hours=DEFAULT_VACATION_AFTER_H)
        duration = timedelta(minutes=DEFAULT_OVERRIDE_DURATION_MIN)
    return AutoSettings(
        persons=_strings(options.get(CONF_PERSONS)),
        away_delay=away_delay,
        vacation_after=vacation_after,
        night=NightSettings(
            methods=_methods(night.get(KEY_METHODS), NIGHT_METHODS),
            start=_time(night.get(KEY_START), DEFAULT_NIGHT_START),
            end=_time(night.get(KEY_END), DEFAULT_NIGHT_END),
            sleep_sensors=_strings(night.get(KEY_SLEEP_SENSORS)),
            charging_sensors=_strings(night.get(KEY_CHARGING_SENSORS)),
        ),
        morning=MorningSettings(
            methods=_methods(morning.get(KEY_METHODS), MORNING_METHODS),
            at=_time(morning.get(KEY_TIME), DEFAULT_MORNING_TIME),
            earliest=_time(morning.get(KEY_EARLIEST), DEFAULT_MORNING_EARLIEST),
            motion_sensors=_strings(morning.get(KEY_MOTION_SENSORS)),
            alarm_sensors=_strings(morning.get(KEY_ALARM_SENSORS)),
        ),
        override=OverrideSettings(
            until=until if until in UNTIL_MODES else DEFAULT_OVERRIDE_UNTIL,
            duration=duration,
        ),
    )


# --- Step 4 settings -------------------------------------------------------------------

ALARMO_STATES = (
    "disarmed",
    "armed_home",
    "armed_away",
    "armed_night",
    "armed_vacation",
    "armed_custom_bypass",
)
# Alarmo's arm service uses short mode names.
ALARMO_ARM_MODES = {
    "armed_home": "home",
    "armed_away": "away",
    "armed_night": "night",
    "armed_vacation": "vacation",
    "armed_custom_bypass": "custom",
}
DIRECTIONS = ("both", "to_alarmo", "from_alarmo")
VACATION_STRATEGIES = ("random", "replay")
NOTIFY_EVENTS = (
    "changed_to",
    "any_change",
    "denied",
    "bridge_error",
    "vacation_entered",
    "guest_on",
)


@dataclass(frozen=True, slots=True)
class AlarmoMapping:
    """One row of the Alarmo state <-> role table."""

    state: str
    role: str | None = None
    to_alarmo: bool = False
    from_alarmo: bool = False
    allow_disarm: bool = False  # only meaningful for the "disarmed" row, off by default


@dataclass(frozen=True, slots=True)
class AlarmoSettings:
    """Alarmo bridge settings (off by default)."""

    enabled: bool = False
    direction: str = "both"
    entity_id: str | None = None
    apply_auto: bool = False  # apply rank 2-4 (auto-rule) changes to Alarmo
    mappings: tuple[AlarmoMapping, ...] = ()


@dataclass(frozen=True, slots=True)
class VacationSettings:
    """Vacation simulation settings (off by default)."""

    enabled: bool = False
    roles: tuple[str, ...] = ("vacation",)
    strategy: str = "random"
    lights: tuple[str, ...] = ()
    start: time = time(18, 0)
    end: time = time(23, 0)
    min_on: timedelta = timedelta(minutes=20)
    max_on: timedelta = timedelta(minutes=90)
    min_gap: timedelta = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class NotifyRule:
    """One notification rule."""

    event: str
    role: str | None = None  # for changed_to
    targets: tuple[str, ...] = ()  # notify entity ids
    services: tuple[str, ...] = ()  # notify service names (without "notify.")
    message: str = ""
    title: str = ""


@dataclass(frozen=True, slots=True)
class NotifySettings:
    """Notification settings. No rules means no notifications."""

    rules: tuple[NotifyRule, ...] = ()
    rate_limit: timedelta = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class MirrorSettings:
    """Temporary migration aid: write the active mode to an old input_select (off)."""

    enabled: bool = False
    entity_id: str | None = None
    mapping: Mapping[str, str] = field(default_factory=dict)  # role id -> input_select option
    overlays: bool = False  # also write overlay options ("Mirror overlays"); off by default


@dataclass(frozen=True, slots=True)
class IntegrationSettings:
    """Step 4 settings."""

    actions_timeout: float = 30.0
    alarmo: AlarmoSettings = field(default_factory=AlarmoSettings)
    vacation: VacationSettings = field(default_factory=VacationSettings)
    notify: NotifySettings = field(default_factory=NotifySettings)
    history_max: int = 500
    mirror: MirrorSettings = field(default_factory=MirrorSettings)


def _bool(raw: Any) -> bool:
    return bool(raw) if isinstance(raw, bool) else False


def parse_integration_settings(options: Mapping[str, Any]) -> IntegrationSettings:
    """Parse the Step 4 options, falling back to safe defaults (everything off)."""
    from .const import (
        CONF_ACTIONS_TIMEOUT,
        CONF_ALARMO,
        CONF_HISTORY,
        CONF_MIRROR,
        CONF_NOTIFY,
        CONF_VACATION_SIM,
        DEFAULT_ACTIONS_TIMEOUT_S,
        DEFAULT_HISTORY_MAX,
        DEFAULT_NOTIFY_RATE_LIMIT_S,
    )

    def number(raw: Any, default: float) -> float:
        try:
            return float(raw)
        except TypeError, ValueError:
            return default

    alarmo_raw = options.get(CONF_ALARMO) or {}
    mappings: list[AlarmoMapping] = []
    for raw in alarmo_raw.get("mappings") or []:
        if not isinstance(raw, Mapping) or raw.get("state") not in ALARMO_STATES:
            continue
        mappings.append(
            AlarmoMapping(
                state=raw["state"],
                role=raw.get("role") or None,
                to_alarmo=_bool(raw.get("to_alarmo")),
                from_alarmo=_bool(raw.get("from_alarmo")),
                allow_disarm=_bool(raw.get("allow_disarm")),
            )
        )
    direction = alarmo_raw.get("direction", "both")
    alarmo = AlarmoSettings(
        enabled=_bool(alarmo_raw.get("enabled")),
        direction=direction if direction in DIRECTIONS else "both",
        entity_id=alarmo_raw.get("entity_id") or None,
        apply_auto=_bool(alarmo_raw.get("apply_auto")),
        mappings=tuple(mappings),
    )

    vac = options.get(CONF_VACATION_SIM) or {}
    default_vac = VacationSettings()
    vacation = VacationSettings(
        enabled=_bool(vac.get("enabled")),
        roles=_strings(vac.get("roles")) or default_vac.roles,
        strategy=str(vac["strategy"]) if vac.get("strategy") in VACATION_STRATEGIES else "random",
        lights=_strings(vac.get("lights")),
        start=_time(vac.get("start"), "18:00:00"),
        end=_time(vac.get("end"), "23:00:00"),
        min_on=timedelta(minutes=number(vac.get("min_on_min"), 20)),
        max_on=timedelta(minutes=number(vac.get("max_on_min"), 90)),
        min_gap=timedelta(minutes=number(vac.get("min_gap_min"), 10)),
    )

    notify_raw = options.get(CONF_NOTIFY) or {}
    rules: list[NotifyRule] = []
    for raw in notify_raw.get("rules") or []:
        if not isinstance(raw, Mapping) or raw.get("event") not in NOTIFY_EVENTS:
            continue
        rules.append(
            NotifyRule(
                event=raw["event"],
                role=raw.get("role") or None,
                targets=_strings(raw.get("targets")),
                services=_strings(raw.get("services")),
                message=str(raw.get("message") or ""),
                title=str(raw.get("title") or ""),
            )
        )
    notify = NotifySettings(
        rules=tuple(rules),
        rate_limit=timedelta(
            seconds=max(0.0, number(notify_raw.get("rate_limit_s"), DEFAULT_NOTIFY_RATE_LIMIT_S))
        ),
    )
    history = options.get(CONF_HISTORY) or {}
    mirror_raw = options.get(CONF_MIRROR) or {}
    raw_map = mirror_raw.get("mapping")
    mirror = MirrorSettings(
        enabled=_bool(mirror_raw.get("enabled")),
        entity_id=mirror_raw.get("entity_id") or None,
        overlays=_bool(mirror_raw.get("overlays")),
        mapping={str(k): str(v) for k, v in raw_map.items()}
        if isinstance(raw_map, Mapping)
        else {},
    )
    return IntegrationSettings(
        actions_timeout=max(
            1.0, number(options.get(CONF_ACTIONS_TIMEOUT), DEFAULT_ACTIONS_TIMEOUT_S)
        ),
        alarmo=alarmo,
        vacation=vacation,
        notify=notify,
        mirror=mirror,
        history_max=int(
            max(10, min(5000, number(history.get("max_entries"), DEFAULT_HISTORY_MAX)))
        ),
    )
