"""Mirror to the old input_select (temporary migration aid)."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .helpers import call, setup_entry

ENTITY = "input_select.house"
OPTIONS = ["Home", "Night", "Out", "Guests"]
MAPPING = {"home": "Home", "night": "Night", "away": "Out", "guest": "Guests"}


async def _setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    *,
    enabled: bool = True,
    mapping: dict[str, str] | None = None,
    options: list[str] | None = None,
    create: bool = True,
    overlays: bool | None = None,
):
    if create:
        assert await async_setup_component(
            hass,
            "input_select",
            {"input_select": {"house": {"options": options or OPTIONS, "initial": "Home"}}},
        )
        await hass.async_block_till_done()
    cfg: dict[str, Any] = {"enabled": enabled, "entity_id": ENTITY, "mapping": mapping or MAPPING}
    if overlays is not None:
        cfg["overlays"] = overlays
    return await setup_entry(hass, freezer, {"mirror": cfg})


def _failures(entry) -> list[dict[str, Any]]:
    return [
        e["bridge"][0]
        for e in entry.runtime_data.history.entries
        if e["kind"] == "system" and e["rule"] == "mirror_failed"
    ]


async def test_off_by_default(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Without the setting nothing is written to any input_select."""
    assert await async_setup_component(
        hass, "input_select", {"input_select": {"house": {"options": OPTIONS, "initial": "Home"}}}
    )
    await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Home"


async def test_overlays_are_not_mirrored_by_default(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """ "Mirror overlays" is off unless set: only the primary's option is ever written."""
    entry = await _setup(hass, freezer)  # mapping contains an option for guest; setting absent
    assert entry.runtime_data.mirror._cfg.overlays is False
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Night"
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Night"  # guest not written
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Night"
    assert _failures(entry) == []


async def test_mirror_overlays_on_writes_overlay_then_primary_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """On: the overlay's option is written while active; at its end the primary's is."""
    entry = await _setup(hass, freezer, overlays=True)
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Night"
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Guests"
    await call(hass, "set_mode", {"mode": "away"})  # primary changes under the overlay
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Guests"
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Out"  # the CURRENT primary, not the old one
    assert _failures(entry) == []


async def test_mirror_overlay_without_matching_option_keeps_primary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An overlay with no option is not a failure: the primary's option stays."""
    mapping = {k: v for k, v in MAPPING.items() if k != "guest"}
    entry = await _setup(hass, freezer, overlays=True, mapping=mapping)
    await call(hass, "set_mode", {"mode": "night"})
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Night"
    assert _failures(entry) == []


async def test_mirror_two_overlays_most_recently_activated_wins(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With two overlays active the one switched on last wins; ending it falls back."""
    options = ["Home", "Night", "Out", "Guests", "Quiet"]
    mapping = {**MAPPING, "dnd": "Quiet"}
    await _setup(hass, freezer, overlays=True, mapping=mapping, options=options)
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Guests"
    await call(hass, "set_overlay", {"overlay": "dnd", "active": True})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Quiet"  # dnd was activated last
    await call(hass, "set_overlay", {"overlay": "dnd", "active": False})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Guests"  # the remaining overlay
    # Opposite order: dnd first, guest last -> guest wins.
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await call(hass, "set_overlay", {"overlay": "dnd", "active": True})
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Guests"
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await call(hass, "set_overlay", {"overlay": "dnd", "active": False})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Home"


async def test_option_name_that_does_not_match(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An option that no longer exists is not written; the failure is in the history."""
    entry = await _setup(hass, freezer, mapping={**MAPPING, "night": "Nite"})
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Home"  # unchanged, nothing invented
    assert _failures(entry) == [
        {"reason": "option_not_in_input_select", "role": "night", "option": "Nite"}
    ]


async def test_option_matching_is_exact(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A different letter case is a different option: nothing is written."""
    entry = await _setup(hass, freezer, mapping={**MAPPING, "away": "out"})
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "Home"
    assert _failures(entry)[-1]["reason"] == "option_not_in_input_select"


async def test_unmapped_role_and_missing_entity(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A role without an option, or a missing input_select, is recorded, not hidden."""
    entry = await _setup(hass, freezer, mapping={"home": "Home"})
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert _failures(entry)[-1]["reason"] == "no_option_mapped"

    hass.states.async_remove(ENTITY)
    await call(hass, "set_mode", {"mode": "home"})
    await hass.async_block_till_done()
    assert _failures(entry)[-1]["reason"] == "input_select_missing"


async def test_no_write_when_already_there(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """If the input_select already shows the option, nothing is written (no state change)."""
    await _setup(hass, freezer)
    hass.states.async_set(ENTITY, "Night", hass.states.get(ENTITY).attributes)
    seen: list[Any] = []
    hass.bus.async_listen(
        "call_service",
        lambda e: seen.append(e.data) if e.data["domain"] == "input_select" else None,
    )
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert seen == []


async def test_one_direction_and_loop_guard(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Home Modes never reads the input_select; a ping-pong automation is stopped."""
    entry = await _setup(hass, freezer)
    # Changing the input_select by hand does not change the house mode.
    hass.states.async_set(ENTITY, "Out", hass.states.get(ENTITY).attributes)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.data.primary == "home"

    ping_pong = [
        {
            "id": "p1",
            "trigger": {"platform": "state", "entity_id": ENTITY, "to": "Night"},
            "action": {"action": "home_modes.set_mode", "data": {"mode": "away"}},
        },
        {
            "id": "p2",
            "trigger": {"platform": "state", "entity_id": ENTITY, "to": "Out"},
            "action": {"action": "home_modes.set_mode", "data": {"mode": "night"}},
        },
    ]
    assert await async_setup_component(hass, "automation", {"automation": ping_pong})
    await hass.async_block_till_done()
    await call(hass, "set_mode", {"mode": "night"})
    for _ in range(10):
        await hass.async_block_till_done()
    primaries = [e for e in entry.runtime_data.history.entries if e["kind"] == "primary"]
    assert len(primaries) <= 6  # stopped by the action-loop limit, not endless
    assert any(
        e["kind"] == "system" and e["rule"] == "action_loop_blocked"
        for e in entry.runtime_data.history.entries
    )
