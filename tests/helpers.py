"""Shared helpers for the Step 3 automation tests."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.home_modes.const import DOMAIN
from custom_components.home_modes.models import HomeModesState

from .conftest import make_entry

NOON = "2026-11-12 12:00:00+00:00"


async def setup_entry(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    options: dict[str, Any] | None = None,
    *,
    start: str = NOON,
    states: dict[str, str] | None = None,
    derived: bool = False,
) -> MockConfigEntry:
    """Freeze time (UTC), preset entity states, then set up the integration."""
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(start)
    for entity_id, state in (states or {}).items():
        hass.states.async_set(entity_id, state)
    entry = make_entry(options=options, derived=derived)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, **delta: float) -> None:
    """Move frozen time forward and fire due timers."""
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Restart the integration (unload flushes the state to storage)."""
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


def data(entry: MockConfigEntry) -> HomeModesState:
    """Return the current runtime state."""
    return entry.runtime_data.coordinator.data


def primary(entry: MockConfigEntry) -> str:
    """Return the current primary role id."""
    return data(entry).primary


async def call(
    hass: HomeAssistant,
    service: str,
    payload: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    """Call a Home Modes service, optionally as a user."""
    await hass.services.async_call(
        DOMAIN,
        service,
        payload or {},
        blocking=True,
        context=Context(user_id=user_id) if user_id else Context(),
    )


def presence_options(
    persons: list[str] | None = None, *, away: float = 4, vacation: float = 24, **extra: Any
) -> dict[str, Any]:
    """Build presence options."""
    return {
        "persons": persons or ["person.anna", "person.ben"],
        "away_delay_min": away,
        "vacation_after_h": vacation,
        **extra,
    }


NIGHT_WINDOW = {"methods": ["time_window"], "start": "22:00:00", "end": "06:00:00"}


def roles_without(*disabled: str) -> list[dict[str, Any]]:
    """Return the extended preset roles (derived disabled) with extra roles disabled."""
    return [
        {**r, "enabled": r["enabled"] and r["id"] not in disabled}
        for r in make_entry(derived=False).options["roles"]
    ]


def set_state(entry: MockConfigEntry, **fields: Any) -> None:
    """Replace fields of the runtime state (test setup only)."""
    from dataclasses import replace

    coordinator = entry.runtime_data.coordinator
    coordinator.async_apply_state(replace(coordinator.data, **fields))
