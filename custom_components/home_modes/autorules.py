"""Auto-rule orchestrator: triggers, timers, overrides and startup catch-up."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    MORNING_ALARM,
    MORNING_TIME,
    NIGHT_TIME_WINDOW,
    ROLE_ALL_AWAY,
    ROLE_ALL_HOME,
    ROLE_AWAY,
    ROLE_HOME,
    ROLE_VACATION,
)
from .coordinator import HomeModesCoordinator
from .engine import ChangeEngine
from .models import (
    SOURCE_RANKS,
    AutoCandidate,
    ChangeResult,
    ChangeSource,
    ChangeStatus,
    HomeModesState,
    OverrideMode,
    RoleKind,
)
from .night import (
    GROUP_ALARM,
    GROUP_CHARGING,
    GROUP_MOTION,
    GROUP_PRESENCE,
    GROUP_SLEEP,
    GROUP_TIME,
    alarm_time,
    is_charging,
    is_on,
    morning_candidates,
    next_occurrence,
    night_candidates,
)
from .presence import PresenceTracker

_LOGGER = logging.getLogger(__name__)

RULE_PRESENCE_AWAY = "presence_away"
RULE_PRESENCE_ALL_AWAY = "presence_all_away"
RULE_PRESENCE_VACATION = "presence_vacation"
RULE_PRESENCE_ARRIVAL = "presence_arrival"
RULE_PRESENCE_ALL_HOME = "presence_all_home"
RULE_PRESENCE_ALL_HOME_END = "presence_all_home_end"

_AWAY_SET = frozenset({ROLE_AWAY, ROLE_ALL_AWAY, ROLE_VACATION})

# Timer keys
_T_NIGHT = "night_start"
_T_MORNING = "morning_time"
_T_ALARM = "alarm"
_T_OVERRIDE = "override"
_T_TEMPORARY = "temporary"
_T_AWAY = "away"
_T_VACATION = "vacation"


class AutoRules:
    """Evaluates auto-rules and owns every timer.

    Timers are derived from absolute timestamps stored in the state (override,
    temporary, all_away_since) or from the options (schedule), so they are
    re-armed after a restart. Anything that expired while Home Assistant was
    down is applied once at startup (temporary expiry, override expiry, then one
    evaluation of all rules in rank order).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: HomeModesCoordinator,
        engine: ChangeEngine,
        tracker: PresenceTracker,
    ) -> None:
        """Initialize the orchestrator."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.engine = engine
        self.tracker = tracker
        self._eval_lock = asyncio.Lock()
        self._timers: dict[str, tuple[datetime, CALLBACK_TYPE]] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._started = False
        engine.evaluator = self.async_evaluate

    # --- lifecycle ----------------------------------------------------------

    @callback
    def async_setup(self) -> None:
        """Subscribe to sensors, presence and state changes."""
        settings = self.coordinator.settings
        self.tracker.async_start()
        self._unsubs.append(self.tracker.async_add_listener(self._on_presence))
        self._unsubs.append(self.coordinator.async_add_listener(self._on_state_update))
        entities = {
            *settings.night.sleep_sensors,
            *settings.night.charging_sensors,
            *settings.morning.motion_sensors,
            *settings.morning.alarm_sensors,
        }
        if entities:
            self._unsubs.append(
                async_track_state_change_event(self.hass, sorted(entities), self._on_sensor)
            )
        self._unsubs.append(
            self.hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, self._on_core_config_update)
        )
        self._unsubs.append(async_at_started(self.hass, self._async_startup))

    @callback
    def _on_core_config_update(self, event: Event) -> None:
        """Re-arm the time-of-day timers when the time zone changes.

        Armed timers are absolute instants; after a time zone change the instant of "22:00"
        is a different one.
        """
        if "time_zone" not in event.data:
            return
        self._rearm()
        if self._started:
            self._spawn(self.async_evaluate(frozenset({GROUP_TIME})), "home_modes time zone")

    @callback
    def async_stop(self) -> None:
        """Cancel every subscription and timer."""
        self._started = False
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self.tracker.async_stop()
        for _, cancel in self._timers.values():
            cancel()
        self._timers.clear()

    async def _async_startup(self, hass: HomeAssistant) -> None:
        """Catch up on everything that expired while Home Assistant was down."""
        self.tracker.async_refresh()
        self._sync_all_away_since()
        now = dt_util.utcnow()
        state = self.coordinator.data
        if state.temporary is not None and state.temporary.until <= now:
            await self.engine.async_expire_temporary()
        override = self.coordinator.data.override
        if override is not None and not override.is_active(now):
            await self.engine.async_clear_override()
        self._started = True
        await self.async_evaluate()
        self._rearm()

    # --- evaluation ---------------------------------------------------------

    async def async_evaluate(
        self, groups: frozenset[str] | None = None, *, motion_event: bool = False
    ) -> ChangeResult | None:
        """Evaluate auto-rules (all groups when groups is None); highest rank wins."""
        if not self.coordinator.data.auto_enabled:
            return None
        async with self._eval_lock:
            now = dt_util.utcnow()
            for candidate in self._candidates(now, groups, motion_event):
                result = await self._async_apply(candidate, now)
                if result.status in (ChangeStatus.APPLIED, ChangeStatus.IGNORED):
                    return result
            return None

    def _candidates(
        self, now: datetime, groups: frozenset[str] | None, motion_event: bool
    ) -> list[AutoCandidate]:
        state = self.coordinator.data
        settings = self.coordinator.settings
        found = [
            *night_candidates(self.hass, settings, state, now, groups),
            *morning_candidates(self.hass, settings, state, now, groups, motion_event=motion_event),
            *self._presence_candidates(state, now, groups),
        ]
        usable = [c for c in found if self._usable(c.role)]
        # Stable sort: lower rank number first, declaration order within a rank.
        return sorted(usable, key=lambda c: SOURCE_RANKS[c.source])

    def _usable(self, role_id: str) -> bool:
        """Auto-rules never target missing or disabled roles (they are skipped)."""
        role = self.coordinator.role(role_id)
        return role is not None and role.enabled and role.kind is not RoleKind.OVERLAY

    def _presence_candidates(
        self, state: HomeModesState, now: datetime, groups: frozenset[str] | None
    ) -> list[AutoCandidate]:
        if groups is not None and GROUP_PRESENCE not in groups:
            return []
        settings = self.coordinator.settings
        tracker = self.tracker
        primary = state.primary
        found: list[AutoCandidate] = []
        if tracker.all_away is False and primary in _AWAY_SET:
            found.append(AutoCandidate(ChangeSource.PRESENCE, RULE_PRESENCE_ARRIVAL, ROLE_HOME))
        since = state.all_away_since
        if tracker.all_away is True and since is not None:
            if now >= since + settings.vacation_after and primary != ROLE_VACATION:
                found.append(
                    AutoCandidate(ChangeSource.PRESENCE, RULE_PRESENCE_VACATION, ROLE_VACATION)
                )
            if now >= since + settings.away_delay and primary not in _AWAY_SET:
                all_away_role = self.coordinator.role(ROLE_ALL_AWAY)
                if all_away_role is not None and all_away_role.enabled:
                    found.append(
                        AutoCandidate(ChangeSource.PRESENCE, RULE_PRESENCE_ALL_AWAY, ROLE_ALL_AWAY)
                    )
                else:
                    found.append(
                        AutoCandidate(ChangeSource.PRESENCE, RULE_PRESENCE_AWAY, ROLE_AWAY)
                    )
        if tracker.all_home is True and primary == ROLE_HOME:
            found.append(
                AutoCandidate(ChangeSource.PRESENCE, RULE_PRESENCE_ALL_HOME, ROLE_ALL_HOME)
            )
        if tracker.all_home is False and primary == ROLE_ALL_HOME:
            found.append(
                AutoCandidate(ChangeSource.PRESENCE, RULE_PRESENCE_ALL_HOME_END, ROLE_HOME)
            )
        return found

    async def _async_apply(self, candidate: AutoCandidate, now: datetime) -> ChangeResult:
        override = self.coordinator.data.override
        if (
            override is not None
            and override.mode is OverrideMode.NEXT_AUTO
            and override.is_active(now)
        ):
            # The next auto-rule trigger ends a "next_auto" override and then applies.
            await self.engine.async_clear_override()
        return await self.engine.async_set_primary(
            candidate.role, candidate.source, rule=candidate.rule
        )

    # --- event handlers -----------------------------------------------------

    def _spawn(self, coro: Coroutine[Any, Any, object], name: str) -> None:
        self.entry.async_create_task(self.hass, coro, name)

    @callback
    def _on_presence(self) -> None:
        self._sync_all_away_since()
        self._spawn(self.async_evaluate(frozenset({GROUP_PRESENCE})), "home_modes presence")

    @callback
    def _sync_all_away_since(self) -> None:
        """Track continuous all_away: set on entry, clear when somebody is home."""
        state = self.coordinator.data
        all_away = self.tracker.all_away
        if all_away is True and state.all_away_since is None:
            self.coordinator.async_apply_state(replace(state, all_away_since=dt_util.utcnow()))
        elif all_away is False and state.all_away_since is not None:
            self.coordinator.async_apply_state(replace(state, all_away_since=None))

    @callback
    def _on_state_update(self) -> None:
        if self._started:
            self._rearm()

    @callback
    def _on_sensor(self, event: Event[EventStateChangedData]) -> None:
        settings = self.coordinator.settings
        entity_id = event.data["entity_id"]
        new, old = event.data["new_state"], event.data["old_state"]
        if new is None:
            return
        if entity_id in settings.night.sleep_sensors and is_on(new) and not is_on(old):
            self._spawn(self.async_evaluate(frozenset({GROUP_SLEEP})), "home_modes sleep")
        if (
            entity_id in settings.night.charging_sensors
            and is_charging(new)
            and not is_charging(old)
        ):
            self._spawn(self.async_evaluate(frozenset({GROUP_CHARGING})), "home_modes charging")
        if entity_id in settings.morning.motion_sensors and is_on(new) and not is_on(old):
            self._spawn(
                self.async_evaluate(frozenset({GROUP_MOTION}), motion_event=True),
                "home_modes motion",
            )
        if entity_id in settings.morning.alarm_sensors:
            self._rearm()
            self._spawn(self.async_evaluate(frozenset({GROUP_ALARM})), "home_modes alarm")

    # --- timers -------------------------------------------------------------

    def _targets(self, now: datetime) -> dict[str, datetime]:
        """Return the absolute time of every timer that should be armed."""
        settings = self.coordinator.settings
        state = self.coordinator.data
        targets: dict[str, datetime] = {}
        if NIGHT_TIME_WINDOW in settings.night.methods:
            targets[_T_NIGHT] = next_occurrence(now, settings.night.start)
        if MORNING_TIME in settings.morning.methods:
            targets[_T_MORNING] = next_occurrence(now, settings.morning.at)
        if MORNING_ALARM in settings.morning.methods:
            future = [
                ts
                for entity_id in settings.morning.alarm_sensors
                if (ts := alarm_time(self.hass.states.get(entity_id))) is not None and ts > now
            ]
            if future:
                targets[_T_ALARM] = min(future)
        override = state.override
        if override is not None and override.until is not None and override.until > now:
            targets[_T_OVERRIDE] = override.until
        if state.temporary is not None and state.temporary.until > now:
            targets[_T_TEMPORARY] = state.temporary.until
        if state.all_away_since is not None:
            for key, delta in (
                (_T_AWAY, settings.away_delay),
                (_T_VACATION, settings.vacation_after),
            ):
                due = state.all_away_since + delta
                if due > now:
                    targets[key] = due
        return targets

    @callback
    def timer_summary(self) -> dict[str, str]:
        """Return the armed timers (name -> due time, ISO format) for diagnostics."""
        return {key: due.isoformat() for key, (due, _cancel) in sorted(self._timers.items())}

    @callback
    def _rearm(self) -> None:
        """Create, move or cancel timers so they match the current targets."""
        now = dt_util.utcnow()
        targets = self._targets(now)
        for key in list(self._timers):
            current, cancel = self._timers[key]
            if key not in targets and current <= now:
                continue  # due: its job is about to run, do not cancel it
            if key not in targets or targets[key] != current:
                cancel()
                del self._timers[key]
        for key, when in targets.items():
            if key not in self._timers:
                self._timers[key] = (
                    when,
                    async_track_point_in_utc_time(self.hass, self._make_job(key), when),
                )

    def _make_job(self, key: str) -> Callable[[datetime], Coroutine[Any, Any, None]]:
        async def _fire(_now: datetime) -> None:
            self._timers.pop(key, None)
            await self._async_timer(key)
            self._rearm()

        return _fire

    async def _async_timer(self, key: str) -> None:
        if key == _T_TEMPORARY:
            await self.engine.async_expire_temporary()
        elif key == _T_OVERRIDE:
            state = self.coordinator.data
            override = state.override
            # With a pending temporary mode its expiry clears the override itself.
            if (
                state.temporary is None
                and override is not None
                and not override.is_active(dt_util.utcnow())
            ):
                await self.engine.async_clear_override()
                await self.async_evaluate()
        elif key in (_T_NIGHT, _T_MORNING):
            await self.async_evaluate(frozenset({GROUP_TIME}))
        elif key == _T_ALARM:
            await self.async_evaluate(frozenset({GROUP_ALARM}))
        elif key in (_T_AWAY, _T_VACATION):
            await self.async_evaluate(frozenset({GROUP_PRESENCE}))
