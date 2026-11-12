"""Vacation simulation: switches selected lights on and off while nobody is home.

Runs only while the primary mode is one of the selected roles (default: vacation) and the
feature is enabled. It only ever controls the selected lights, remembers the lights it
switched on, switches those off again when the mode ends or the integration unloads, and
keeps absolute timestamps in storage so it survives a restart. It is quiet: the only
trace is a history entry when it starts and when it stops.

Strategies: random (evening window, on-duration, minimum gap) and replay (the same weekday
of last week from the recorder; falls back to random when no history is available).
The recorder is optional and imported only when needed.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.core import Context, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_MINOR_VERSION, STORAGE_SAVE_DELAY, STORAGE_VERSION
from .coordinator import HomeModesCoordinator
from .history import HistoryLog
from .settings import VacationSettings

_LOGGER = logging.getLogger(__name__)

MIN_INTERVAL = timedelta(minutes=1)
REPLAY_DAYS = 7


class VacationSimulator:
    """Keeps the plan and drives the selected lights."""

    def __init__(
        self, hass: HomeAssistant, coordinator: HomeModesCoordinator, history: HistoryLog
    ) -> None:
        """Initialize the simulator."""
        self.hass = hass
        self.coordinator = coordinator
        self.history = history
        entry_id = coordinator.config_entry.entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.vacation",
            minor_version=STORAGE_MINOR_VERSION,
        )
        self.rng = random.Random()
        self._lock = asyncio.Lock()
        self._active = False
        self._plan_day: str | None = None
        # [{"e": entity, "on": iso, "off": iso, "started": bool}]
        self._plan: list[dict[str, Any]] = []
        self._ours: dict[str, str] = {}  # entity -> planned off time (iso)
        self._timer: Callable[[], None] | None = None
        self._unsub_listener: Callable[[], None] | None = None

    @property
    def _cfg(self) -> VacationSettings:
        return self.coordinator.integrations.vacation

    @property
    def active(self) -> bool:
        """Return whether the simulation is running."""
        return self._active

    # --- lifecycle ----------------------------------------------------------

    async def async_setup(self) -> None:
        """Load the stored plan and start following the mode."""
        stored = await self._store.async_load()
        if stored:
            self._active = bool(stored.get("active"))
            self._plan_day = stored.get("day")
            self._plan = [p for p in stored.get("plan", []) if isinstance(p, dict)]
            self._ours = dict(stored.get("ours", {}))
        self._unsub_listener = self.coordinator.async_add_listener(self._on_state)
        await self._async_sync()

    async def async_unload(self) -> None:
        """Stop following; switch off what the simulation switched on."""
        if self._unsub_listener is not None:
            self._unsub_listener()
            self._unsub_listener = None
        async with self._lock:
            if self._active:
                await self._async_stop("unload")
            self._cancel_timer()
        await self._store.async_save(self._data())

    def async_detach(self) -> None:
        """Cancel timers without touching the lights (used to simulate a restart)."""
        if self._unsub_listener is not None:
            self._unsub_listener()
            self._unsub_listener = None
        self._cancel_timer()

    def _data(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "day": self._plan_day,
            "plan": self._plan,
            "ours": self._ours,
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._data, STORAGE_SAVE_DELAY)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    # --- following the mode -------------------------------------------------

    def _wanted(self) -> bool:
        return self._cfg.enabled and self.coordinator.data.primary in self._cfg.roles

    @callback
    def _on_state(self) -> None:
        if self._wanted() != self._active:
            self.coordinator.config_entry.async_create_task(self.hass, self._async_sync())

    async def _async_sync(self) -> None:
        async with self._lock:
            wanted = self._wanted()
            if wanted and not self._active:
                await self._async_start()
            elif not wanted and self._active:
                await self._async_stop("mode_ended")
            elif wanted:
                await self._async_process()  # resume after a restart

    async def _async_start(self) -> None:
        self._active = True
        self.history.async_add_system(
            "vacation_sim_start", {"strategy": self._cfg.strategy, "lights": list(self._cfg.lights)}
        )
        await self._async_plan(dt_util.now().date())
        await self._async_process()

    async def _async_stop(self, reason: str) -> None:
        self._cancel_timer()
        for entity_id in list(self._ours):
            await self._async_light(entity_id, on=False)
        self._ours.clear()
        self._plan = []
        self._plan_day = None
        self._active = False
        self.history.async_add_system("vacation_sim_stop", {"reason": reason})
        self._save()

    # --- planning -----------------------------------------------------------

    def _window(self, day: date) -> tuple[datetime, datetime]:
        tz = dt_util.get_default_time_zone()
        start = datetime.combine(day, self._cfg.start, tzinfo=tz)
        end = datetime.combine(day, self._cfg.end, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    async def _async_plan(self, day: date) -> None:
        plan: list[dict[str, Any]] | None = None
        if self._cfg.strategy == "replay":
            plan = await self._async_replay_plan(day)
            if plan is None:
                _LOGGER.warning(
                    "Vacation simulation: no recorder history available for the replay "
                    "strategy, using the random strategy instead"
                )
        if plan is None:
            plan = self._random_plan(day)
        self._plan = plan
        self._plan_day = day.isoformat()
        self._save()

    def _random_plan(self, day: date) -> list[dict[str, Any]]:
        cfg = self._cfg
        start, end = self._window(day)
        plan: list[dict[str, Any]] = []
        for entity_id in cfg.lights:
            first = self.rng.uniform(0, min(3600.0, (end - start).total_seconds() / 2))
            moment = start + timedelta(seconds=first)
            while moment < end:
                length = timedelta(
                    seconds=self.rng.uniform(cfg.min_on.total_seconds(), cfg.max_on.total_seconds())
                )
                off = min(moment + length, end)
                if off - moment < MIN_INTERVAL:
                    break
                plan.append(self._item(entity_id, moment, off))
                extra = timedelta(seconds=self.rng.uniform(0, cfg.max_on.total_seconds()))
                moment = off + cfg.min_gap + extra
        return plan

    @staticmethod
    def _item(entity_id: str, on: datetime, off: datetime) -> dict[str, Any]:
        return {
            "e": entity_id,
            "on": dt_util.as_utc(on).isoformat(),
            "off": dt_util.as_utc(off).isoformat(),
            "started": False,
        }

    async def _async_replay_plan(self, day: date) -> list[dict[str, Any]] | None:
        """Copy the on-intervals of the same weekday last week, or None if unavailable."""
        tz = dt_util.get_default_time_zone()
        source = day - timedelta(days=REPLAY_DAYS)
        day_start = datetime.combine(source, datetime.min.time(), tzinfo=tz)
        day_end = datetime.combine(source + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        history = await self._async_fetch(list(self._cfg.lights), day_start, day_end)
        if history is None:
            return None
        plan: list[dict[str, Any]] = []
        for entity_id, states in history.items():
            for on, off in self._intervals(states, day_start, day_end):
                shift = timedelta(days=REPLAY_DAYS)
                # wall-clock shift keeps the local time across DST changes
                plan.append(
                    self._item(
                        entity_id, dt_util.as_local(on) + shift, dt_util.as_local(off) + shift
                    )
                )
        return plan or None

    @staticmethod
    def _intervals(
        states: list[State], day_start: datetime, day_end: datetime
    ) -> list[tuple[datetime, datetime]]:
        result: list[tuple[datetime, datetime]] = []
        began: datetime | None = None
        for state in states:
            at = max(state.last_changed, day_start)
            if state.state == "on" and began is None:
                began = at
            elif state.state != "on" and began is not None:
                if at - began >= MIN_INTERVAL:
                    result.append((began, at))
                began = None
        if began is not None and day_end - began >= MIN_INTERVAL:
            result.append((began, day_end))
        return result

    async def _async_fetch(
        self, entity_ids: list[str], start: datetime, end: datetime
    ) -> dict[str, list[State]] | None:
        """Read light history from the recorder (optional dependency)."""
        try:
            from homeassistant.components.recorder import history as recorder_history
            from homeassistant.helpers.recorder import DATA_INSTANCE, get_instance

            if DATA_INSTANCE not in self.hass.data:
                return None
            result = await get_instance(self.hass).async_add_executor_job(
                partial(
                    recorder_history.get_significant_states,
                    self.hass,
                    start,
                    end,
                    entity_ids,
                    include_start_time_state=True,
                    significant_changes_only=False,
                    no_attributes=True,
                )
            )
        except Exception:
            _LOGGER.debug("Vacation simulation: recorder query failed", exc_info=True)
            return None
        states = {e: [s for s in v if isinstance(s, State)] for e, v in result.items()}
        return states or None

    # --- running the plan ---------------------------------------------------

    async def _async_process(self) -> None:
        """Apply everything that is due and arm the timer for the next event."""
        self._cancel_timer()
        now = dt_util.utcnow()
        remaining: list[dict[str, Any]] = []
        for item in self._plan:
            entity_id = item["e"]
            on = dt_util.parse_datetime(item["on"])
            off = dt_util.parse_datetime(item["off"])
            if on is None or off is None:
                continue
            if not item["started"]:
                if off <= now:
                    continue  # never started and already over
                if on <= now:
                    item["started"] = True
                    if await self._async_light_is_on(entity_id):
                        continue  # the user's own light: leave it alone
                    await self._async_light(entity_id, on=True)
                    self._ours[entity_id] = item["off"]
                remaining.append(item)
            elif off <= now:
                if entity_id in self._ours:
                    await self._async_light(entity_id, on=False)
                    del self._ours[entity_id]
            else:
                remaining.append(item)
        self._plan = remaining
        today = dt_util.now().date()
        if not self._plan and self._plan_day != today.isoformat():
            await self._async_plan(today)
            if self._plan:
                await self._async_process()
                return
        self._save()
        self._arm_timer(now)

    def _arm_timer(self, now: datetime) -> None:
        times: list[datetime] = []
        for item in self._plan:
            raw = item["off"] if item["started"] else item["on"]
            if (when := dt_util.parse_datetime(raw)) is not None:
                times.append(when)
        if not times:
            tomorrow = dt_util.now().date() + timedelta(days=1)
            times.append(dt_util.start_of_local_day(tomorrow) + timedelta(seconds=30))
        when = max(min(times), now + timedelta(seconds=1))
        self._timer = async_track_point_in_utc_time(self.hass, self._tick, when)

    async def _tick(self, _now: datetime) -> None:
        self._timer = None
        async with self._lock:
            if self._active:
                await self._async_process()

    async def _async_light_is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == "on"

    async def _async_light(self, entity_id: str, *, on: bool) -> None:
        try:
            await self.hass.services.async_call(
                "light",
                "turn_on" if on else "turn_off",
                {"entity_id": entity_id},
                blocking=True,
                context=Context(),
            )
        except Exception as err:
            _LOGGER.warning(
                "Vacation simulation: %s failed for %s (%s)", on, entity_id, type(err).__name__
            )
