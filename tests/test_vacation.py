"""Vacation simulation: random and replay strategies, start/stop, restart, selected lights."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.home_modes.vacation import VacationSimulator

from .helpers import advance, call, primary, roles_without, setup_entry


@pytest.fixture(autouse=True)
async def _unload_at_end(hass: HomeAssistant):
    """Stop the simulation timers before the test ends."""
    yield
    for entry in hass.config_entries.async_entries("home_modes"):
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


LIGHTS = ["light.living", "light.kitchen"]
CFG = {
    "enabled": True,
    "roles": ["vacation"],
    "strategy": "random",
    "lights": LIGHTS,
    "start": "18:00:00",
    "end": "23:00:00",
    "min_on_min": 20,
    "max_on_min": 40,
    "min_gap_min": 10,
}


class Lights:
    """Fake lights that record every service call with the time it happened."""

    def __init__(self, hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
        self.hass = hass
        self.freezer = freezer
        self.log: list[tuple[datetime, str, str]] = []
        for service, state in (("turn_on", "on"), ("turn_off", "off")):
            hass.services.async_register("light", service, self._handler(service, state))
        for entity in (*LIGHTS, "light.other"):
            hass.states.async_set(entity, "off")

    def _handler(self, service: str, state: str):
        async def handle(call: ServiceCall) -> None:
            entity = call.data["entity_id"]
            self.log.append((dt_util.utcnow(), service, entity))
            self.hass.states.async_set(entity, state)

        return handle

    def touched(self) -> set[str]:
        return {entity for _, _, entity in self.log}


async def _run_to(hass, freezer, hour: int, minute: int = 0, step: int = 60) -> None:
    """Advance in steps (seconds) to a UTC time on 2026-11-12."""
    target = datetime(2026, 11, 12, hour, minute, tzinfo=UTC)
    while dt_util.utcnow() < target:
        await advance(hass, freezer, seconds=step)


async def _start(hass, freezer, strategy="random", seed=1, **cfg):
    lights = Lights(hass, freezer)
    options = {"roles": roles_without(), "vacation_sim": {**CFG, "strategy": strategy, **cfg}}
    entry = await setup_entry(hass, freezer, options)
    entry.runtime_data.vacation.rng = random.Random(seed)
    return entry, lights


async def test_off_by_default_and_wrong_mode(hass, freezer) -> None:
    """Disabled, or a mode that is not selected: nothing happens."""
    lights = Lights(hass, freezer)
    await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 22)
    assert lights.log == []


async def test_random_strategy_window_durations_and_selected_lights(hass, freezer) -> None:
    """Lights go on/off inside the window, within the on-durations, only the selected ones."""
    _entry, lights = await _start(hass, freezer)
    hass.states.async_set("light.other", "on")  # the user's own light stays untouched
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 23, 30)
    assert lights.log, "the simulation switched nothing"
    assert lights.touched() <= set(LIGHTS)
    assert "light.other" not in lights.touched()
    assert hass.states.get("light.other").state == "on"
    for entity in LIGHTS:
        events = [(t, s) for t, s, e in lights.log if e == entity]
        assert [s for _, s in events][::2] == ["turn_on"] * len(events[::2])
        assert len(events) % 2 == 0  # everything switched on was switched off again
        for (on_at, _), (off_at, _) in zip(events[::2], events[1::2], strict=True):
            assert datetime(2026, 11, 12, 18, tzinfo=UTC) <= on_at
            assert off_at <= datetime(2026, 11, 12, 23, tzinfo=UTC) + timedelta(seconds=60)
            assert (
                timedelta(minutes=19) <= off_at - on_at <= timedelta(minutes=41)
                or off_at.hour == 23
            )
        for (off_at, _), (on_at, _) in zip(events[1::2], events[2::2], strict=False):
            assert on_at - off_at >= timedelta(minutes=9)  # min gap
    assert all(hass.states.get(e).state == "off" for e in LIGHTS)


async def test_start_stop_history_only_and_quiet(hass, freezer) -> None:
    """Only start/stop history entries; no notifications; stopping switches its lights off."""
    notify = async_mock_service(hass, "notify", "mobile_app_pixel")
    lights = Lights(hass, freezer)
    options = {
        "roles": roles_without(),
        "vacation_sim": CFG,
        "notify": {"rules": [{"event": "bridge_error", "services": ["mobile_app_pixel"]}]},
    }
    entry = await setup_entry(hass, freezer, options)
    entry.runtime_data.vacation.rng = random.Random(3)
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 20, 30)
    assert any(hass.states.get(e).state == "on" for e in LIGHTS)
    await call(hass, "set_mode", {"mode": "home"})
    await hass.async_block_till_done()
    assert all(hass.states.get(e).state == "off" for e in LIGHTS)
    assert lights.touched() <= set(LIGHTS)
    rules = [e["rule"] for e in entry.runtime_data.history.entries if e["kind"] == "system"]
    assert rules == ["vacation_sim_start", "vacation_sim_stop"]
    assert notify == []
    assert not entry.runtime_data.vacation.active
    # nothing happens any more after the mode ended
    count = len(lights.log)
    await _run_to(hass, freezer, 22)
    assert len(lights.log) == count


async def test_unload_switches_off_what_it_switched_on(hass, freezer) -> None:
    """Unloading the integration turns its lights off again."""
    entry, _lights = await _start(hass, freezer, seed=5)
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 20, 30)
    assert any(hass.states.get(e).state == "on" for e in LIGHTS)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(hass.states.get(e).state == "off" for e in LIGHTS)


async def test_user_light_already_on_is_not_touched(hass, freezer) -> None:
    """A selected light that is already on (not ours) is neither switched on nor off."""
    _entry, lights = await _start(hass, freezer, lights=["light.living"], seed=2)
    hass.states.async_set("light.living", "on")
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 23, 30)
    assert lights.log == []
    assert hass.states.get("light.living").state == "on"


async def test_custom_role_selection(hass, freezer) -> None:
    """The simulation can follow any selected role (here: away)."""
    _entry, lights = await _start(hass, freezer, roles=["away"])
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 20)
    assert lights.log == []
    await call(hass, "set_mode", {"mode": "away"})
    await _run_to(hass, freezer, 22)
    assert lights.log


async def test_restart_resumes_from_absolute_timestamps(hass, freezer) -> None:
    """After a restart the stored plan continues and the lights it switched on go off."""
    entry, _lights = await _start(hass, freezer, seed=7)
    sim = entry.runtime_data.vacation
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 20, 30)
    on_now = [e for e in LIGHTS if hass.states.get(e).state == "on"]
    assert on_now
    await sim._store.async_save(sim._data())  # what the final write at shutdown does
    sim.async_detach()  # restart: timers vanish, lights keep their state
    fresh = VacationSimulator(hass, entry.runtime_data.coordinator, entry.runtime_data.history)
    fresh.rng = random.Random(7)
    await fresh.async_setup()
    assert fresh.active and set(fresh._ours) == set(on_now)
    await _run_to(hass, freezer, 23, 30)
    assert all(hass.states.get(e).state == "off" for e in LIGHTS)
    assert not fresh._ours
    # no second "start" entry was written by the resumed instance
    starts = [e for e in entry.runtime_data.history.entries if e["rule"] == "vacation_sim_start"]
    assert len(starts) == 1
    await fresh.async_unload()


async def test_restart_catches_up_missed_off_time(hass, freezer) -> None:
    """If HA was down past the off time, the light is switched off right after startup."""
    entry, _lights = await _start(hass, freezer, seed=7)
    sim = entry.runtime_data.vacation
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 20, 30)
    on_now = [e for e in LIGHTS if hass.states.get(e).state == "on"]
    await sim._store.async_save(sim._data())
    sim.async_detach()
    freezer.move_to("2026-11-12 23:30:00+00:00")  # down for hours
    fresh = VacationSimulator(hass, entry.runtime_data.coordinator, entry.runtime_data.history)
    await fresh.async_setup()
    await hass.async_block_till_done()
    assert on_now and all(hass.states.get(e).state == "off" for e in on_now)
    await fresh.async_unload()


def _history(entity: str, spans: list[tuple[int, int, int, int]]) -> list[State]:
    """Build recorder-like states for 2026-11-05 (same weekday last week)."""
    day = datetime(2026, 11, 5, tzinfo=UTC)
    states = [State(entity, "off", last_changed=day, last_updated=day)]
    for sh, sm, eh, em in spans:
        on = day.replace(hour=sh, minute=sm)
        off = day.replace(hour=eh, minute=em)
        states.append(State(entity, "on", last_changed=on, last_updated=on))
        states.append(State(entity, "off", last_changed=off, last_updated=off))
    return states


async def test_replay_strategy_copies_last_weeks_pattern(hass, freezer, monkeypatch) -> None:
    """Replay switches the light on/off at last week's times (same weekday)."""
    seen: dict[str, object] = {}

    async def fake_fetch(self, entity_ids, start, end):
        seen.update(entities=entity_ids, start=start, end=end)
        return {
            "light.living": _history("light.living", [(19, 0, 20, 0), (21, 0, 21, 30)]),
            "light.kitchen": _history("light.kitchen", []),
        }

    monkeypatch.setattr(VacationSimulator, "_async_fetch", fake_fetch)
    _entry, lights = await _start(hass, freezer, strategy="replay")
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 22, step=30)
    assert seen["start"] == datetime(2026, 11, 5, tzinfo=UTC)  # exactly 7 days earlier
    assert seen["entities"] == LIGHTS
    on_off = [(t.hour, t.minute, s) for t, s, e in lights.log if e == "light.living"]
    assert on_off == [
        (19, 0, "turn_on"),
        (20, 0, "turn_off"),
        (21, 0, "turn_on"),
        (21, 30, "turn_off"),
    ]
    assert "light.kitchen" not in lights.touched()


async def test_replay_starts_in_the_middle_of_an_interval(hass, freezer, monkeypatch) -> None:
    """Starting at 19:30 inside last week's 19:00-20:00 span turns the light on right away."""

    async def fake_fetch(self, entity_ids, start, end):
        return {"light.living": _history("light.living", [(19, 0, 20, 0)])}

    monkeypatch.setattr(VacationSimulator, "_async_fetch", fake_fetch)
    _entry, _lights = await _start(hass, freezer, strategy="replay", lights=["light.living"])
    freezer.move_to("2026-11-12 19:30:00+00:00")
    await call(hass, "set_mode", {"mode": "vacation"})
    assert hass.states.get("light.living").state == "on"
    await _run_to(hass, freezer, 20, 5)
    assert hass.states.get("light.living").state == "off"


async def test_replay_falls_back_to_random_without_history(
    hass, freezer, monkeypatch, caplog
) -> None:
    """No history (None) -> random plan and a logged warning."""

    async def no_history(self, entity_ids, start, end):
        return None

    monkeypatch.setattr(VacationSimulator, "_async_fetch", no_history)
    _entry, lights = await _start(hass, freezer, strategy="replay", seed=4)
    with caplog.at_level(logging.WARNING):
        await call(hass, "set_mode", {"mode": "vacation"})
    assert "using the random strategy" in caplog.text
    await _run_to(hass, freezer, 23, 30)
    assert lights.log


async def test_replay_without_recorder_falls_back(hass, freezer, caplog) -> None:
    """The recorder is optional: not set up in this test -> random fallback."""
    entry, _lights = await _start(hass, freezer, strategy="replay", seed=4)
    with caplog.at_level(logging.WARNING):
        await call(hass, "set_mode", {"mode": "vacation"})
    assert "using the random strategy" in caplog.text
    assert entry.runtime_data.vacation._plan


async def test_replay_empty_history_falls_back(hass, freezer, monkeypatch, caplog) -> None:
    """History without any 'on' time -> random fallback."""

    async def empty(self, entity_ids, start, end):
        return {"light.living": _history("light.living", [])}

    monkeypatch.setattr(VacationSimulator, "_async_fetch", empty)
    _entry, _lights = await _start(hass, freezer, strategy="replay")
    with caplog.at_level(logging.WARNING):
        await call(hass, "set_mode", {"mode": "vacation"})
    assert "using the random strategy" in caplog.text


async def test_next_day_is_planned(hass, freezer) -> None:
    """The simulation keeps going the next evening."""
    entry, lights = await _start(hass, freezer, seed=9)
    await call(hass, "set_mode", {"mode": "vacation"})
    await _run_to(hass, freezer, 23, 30, step=300)
    first_day = len(lights.log)
    freezer.move_to("2026-11-13 12:00:00+00:00")
    await advance(hass, freezer, seconds=1)
    target = datetime(2026, 11, 13, 23, 30, tzinfo=UTC)
    while dt_util.utcnow() < target:
        await advance(hass, freezer, seconds=300)
    assert len(lights.log) > first_day
    assert all(hass.states.get(e).state == "off" for e in LIGHTS)
    assert primary(entry) == "vacation"
