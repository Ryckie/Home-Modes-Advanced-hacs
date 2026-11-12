"""Replay strategy against the real recorder (no mocks of the history API)."""

from __future__ import annotations

import pytest

from .helpers import call, setup_entry
from .test_vacation import CFG, Lights, _run_to, roles_without


@pytest.fixture
def recorder_db_url() -> str:
    """Use an in-memory database (the root conftest sets up hass before this module can)."""
    return "sqlite://"


async def test_replay_with_real_recorder(hass, freezer, async_test_recorder) -> None:
    """Replay reads last week's real recorder history (same weekday, 7 days earlier)."""
    from homeassistant.components.recorder import Recorder
    from homeassistant.helpers.recorder import get_instance
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    await hass.config.async_set_time_zone("UTC")
    async with async_test_recorder(hass):
        lights = Lights(hass, freezer)
        for stamp, state in (
            ("2026-11-05 18:00:00+00:00", "off"),
            ("2026-11-05 19:00:00+00:00", "on"),
            ("2026-11-05 20:00:00+00:00", "off"),
        ):
            freezer.move_to(stamp)
            hass.states.async_set("light.living", state)
            await async_wait_recording_done(hass)
        assert isinstance(get_instance(hass), Recorder)
        lights.log.clear()
        options = {
            "roles": roles_without(),
            "vacation_sim": {**CFG, "strategy": "replay", "lights": ["light.living"]},
        }
        entry = await setup_entry(hass, freezer, options)
        await call(hass, "set_mode", {"mode": "vacation"})
        await _run_to(hass, freezer, 20, 5, step=30)
        on_off = [(t.hour, t.minute, s) for t, s, e in lights.log if e == "light.living"]
        assert on_off == [(19, 0, "turn_on"), (20, 0, "turn_off")]
        assert entry.runtime_data.vacation.active
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
