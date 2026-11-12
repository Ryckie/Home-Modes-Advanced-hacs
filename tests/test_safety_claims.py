"""Strengthened safety checks added by the final verification pass."""

from __future__ import annotations

import json

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from .fake_alarmo import FakeAlarmo
from .helpers import advance, call, presence_options, primary, setup_entry
from .test_alarmo import _mappings, _options

HOME2 = {"person.anna": "home", "person.ben": "home"}
AWAY2 = {"person.anna": "not_home", "person.ben": "not_home"}


async def test_real_presence_and_expiry_changes_never_touch_alarmo(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Real presence changes and a real temporary expiry leave Alarmo alone (defaults)."""
    fake = FakeAlarmo(hass, state="armed_home")
    options = {**_options(), **presence_options()}
    entry = await setup_entry(hass, freezer, options, states=HOME2)

    for entity_id, state in AWAY2.items():  # everyone leaves: presence rule (rank 4)
        hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"
    assert fake.calls == []

    for entity_id, state in HOME2.items():  # everyone returns
        hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert fake.calls == []
    assert hass.states.get("alarm_control_panel.alarmo").state == "armed_home"

    # An explicit temporary mode (manual) may arm; its expiry (rank 1, source
    # temporary_expiry) must not touch Alarmo again.
    await call(hass, "set_temporary", {"mode": "night", "duration": {"minutes": 5}})
    calls_after_manual = list(fake.calls)
    await advance(hass, freezer, minutes=6)
    assert primary(entry) == "home"
    assert fake.calls == calls_after_manual
    assert not any(name == "disarm" for name, *_ in fake.calls)


async def test_no_alarmo_code_reaches_a_call_or_a_store(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage
) -> None:
    """No `code` key is ever sent to Alarmo or written to the options or stores."""
    fake = FakeAlarmo(hass, state="disarmed")
    entry = await setup_entry(hass, freezer, _options())
    for mode in ("away", "night", "vacation", "home"):
        await call(hass, "set_mode", {"mode": mode})
    assert fake.calls  # arming really happened
    assert all("code" not in data for _, data, _ in fake.calls)
    assert "code" not in json.dumps(dict(entry.options), default=str)
    await hass.config_entries.async_unload(entry.entry_id)
    stored = json.dumps({k: v for k, v in hass_storage.items() if "home_modes" in k})
    assert stored and '"code"' not in stored


async def test_disarm_mapping_without_switch_blocks_every_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A role mapped to disarmed never disarms without the explicit switch: not for a user,
    an automation call, a schedule, nor with apply_auto on."""
    fake = FakeAlarmo(hass, state="armed_away")
    mappings = _mappings(disarmed={"role": "home", "to_alarmo": True})
    entry = await setup_entry(hass, freezer, _options(apply_auto=True, mappings=mappings))
    engine = entry.runtime_data.engine
    from custom_components.home_modes.models import ChangeSource

    await entry.runtime_data.engine.async_set_primary("night", ChangeSource.SYSTEM, rule="t")
    for source in (ChangeSource.MANUAL, ChangeSource.SCHEDULE, ChangeSource.PRESENCE):
        await engine.async_set_primary("away", source, rule="x")
        await engine.async_set_primary("home", source, rule="x")
    assert not any(name == "disarm" for name, *_ in fake.calls)


async def test_import_with_a_full_mapping_but_no_confirm_writes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A full mapping and a mirror request without confirm change nothing."""
    from homeassistant.setup import async_setup_component

    from .test_migration import _import

    entry = await setup_entry(hass, freezer)
    assert await async_setup_component(
        hass,
        "input_select",
        {"input_select": {"house": {"options": ["Living", "Sleeping"], "initial": "Living"}}},
    )
    await hass.async_block_till_done()
    options_before = json.dumps(dict(entry.options), sort_keys=True, default=str)
    states_before = {s.entity_id: s.state for s in hass.states.async_all()}
    result = await _import(
        hass,
        {
            "entity_id": "input_select.house",
            "mapping": {"Living": "home", "Sleeping": "night"},
            "mirror": True,
            "confirm": False,
        },
    )
    assert result["applied"] is False
    assert json.dumps(dict(entry.options), sort_keys=True, default=str) == options_before
    assert {s.entity_id: s.state for s in hass.states.async_all()} == states_before
    await call(hass, "set_mode", {"mode": "night"})
    assert hass.states.get("input_select.house").state == "Living"  # no mirror was enabled


async def test_late_echo_of_our_own_arming_does_not_flip_the_mode_back(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Away arms Alarmo (exit delay); the user then picks Home; Alarmo's late final state
    (fresh context) is our own echo and must not switch Home Modes back to Away."""
    from homeassistant.const import EVENT_STATE_CHANGED  # noqa: F401
    from pytest_homeassistant_custom_component.common import async_capture_events

    from custom_components.home_modes.const import EVENT_CHANGED

    from .helpers import data

    fake = FakeAlarmo(hass, state="disarmed", exit_delay=30)
    entry = await setup_entry(hass, freezer, _options())
    changes = async_capture_events(hass, EVENT_CHANGED)
    await call(hass, "set_mode", {"mode": "away"})
    await advance(hass, freezer, seconds=5)
    await call(hass, "set_mode", {"mode": "home"})
    fake.finish_arming()  # Alarmo reaches armed_away with a context we cannot recognise
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert len(changes) == 2  # away, then home; no third change from the echo
    assert data(entry).last_trigger.source == "manual"
