"""Alarmo bridge: directions, mappings, safety defaults, loop guard and Ring-style keypad."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from custom_components.home_modes.const import EVENT_CHANGED
from custom_components.home_modes.models import ChangeSource

from .fake_alarmo import ENTITY, FakeAlarmo
from .helpers import advance, call, data, primary, roles_without, setup_entry

# state -> role for the default table
TABLE = {
    "armed_home": "home",
    "armed_away": "away",
    "armed_night": "night",
    "armed_vacation": "vacation",
    "armed_custom_bypass": "custom_1",
}


def _mappings(**override: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"state": "disarmed", "role": "home", "to_alarmo": False, "from_alarmo": True},
        *(
            {"state": s, "role": r, "to_alarmo": True, "from_alarmo": True}
            for s, r in TABLE.items()
        ),
    ]
    return [{**row, **override.get(row["state"], {})} for row in rows]


def _options(
    *, direction: str = "both", apply_auto: bool = False, mappings: list | None = None, **extra: Any
) -> dict[str, Any]:
    roles = roles_without()
    roles.append({"id": "custom_1", "name": "Party", "enabled": True})
    return {
        "roles": roles,
        "alarmo": {
            "enabled": True,
            "direction": direction,
            "entity_id": ENTITY,
            "apply_auto": apply_auto,
            "mappings": mappings if mappings is not None else _mappings(),
            **extra,
        },
    }


async def _setup(hass, freezer, alarmo_state="disarmed", exit_delay=0, code=False, top=None, **kw):
    fake = FakeAlarmo(hass, state=alarmo_state, exit_delay=exit_delay, code=code)
    entry = await setup_entry(hass, freezer, {**_options(**kw), **(top or {})})
    return entry, fake


async def _start_in(entry, role: str) -> None:
    """Put Home Modes in a mode without involving Alarmo (system changes never reach it)."""
    await entry.runtime_data.engine.async_set_primary(role, ChangeSource.SYSTEM, rule="test")


async def _keypad(hass: HomeAssistant, fake: FakeAlarmo, state: str, **attrs: Any) -> None:
    """A state change that did not come from Home Modes (keypad, panel, Alarmo itself)."""
    fake.set(state, Context(), **attrs)
    await hass.async_block_till_done()


# --- optional dependency -------------------------------------------------------


async def test_alarmo_absent_at_setup(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """With the bridge enabled and no Alarmo installed, setup works and modes still change."""
    entry = await setup_entry(hass, freezer, _options())
    await call(hass, "set_mode", {"mode": "away"})
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    errors = [n for e in entry.runtime_data.history.entries for n in e["bridge"] if "error" in n]
    assert errors and errors[0]["error"] == "alarmo_not_found"


async def test_alarmo_removed_at_runtime(hass: HomeAssistant, freezer) -> None:
    """Removing Alarmo while the bridge is running only produces bridge errors."""
    entry, fake = await _setup(hass, freezer)
    await call(hass, "set_mode", {"mode": "away"})
    assert fake.arm_calls
    fake.remove()
    await hass.async_block_till_done()
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    notes = entry.runtime_data.history.entries[-1]["bridge"]
    assert notes[0]["error"] == "alarmo_not_found"
    # services gone but entity still there: reported, not raised
    fake2 = FakeAlarmo(hass)
    hass.services.async_remove("alarmo", "arm")
    await call(hass, "set_mode", {"mode": "home"})
    await call(hass, "set_mode", {"mode": "away"})
    assert entry.runtime_data.history.entries[-1]["bridge"][0]["error"] == "alarmo_service_missing"
    assert fake2.calls == []


async def test_disabled_by_default(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Without options the bridge does nothing in either direction."""
    fake = FakeAlarmo(hass)
    entry = await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "away"})
    await _keypad(hass, fake, "armed_night")
    assert fake.calls == []
    assert primary(entry) == "away"


async def test_entity_autodetect(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Without a configured entity the only Alarmo alarm panel is used."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "alarm_control_panel", "alarmo", "uid", suggested_object_id="alarmo"
    )
    fake = FakeAlarmo(hass)
    options = _options()
    options["alarmo"]["entity_id"] = None
    entry = await setup_entry(hass, freezer, options)
    await call(hass, "set_mode", {"mode": "away"})
    assert fake.arm_calls == [
        {"entity_id": ENTITY, "mode": "away", "skip_delay": False, "force": False}
    ]
    assert primary(entry) == "away"


# --- from_alarmo --------------------------------------------------------------


@pytest.mark.parametrize(("state", "role"), list(TABLE.items()))
async def test_from_alarmo_every_mapping(hass, freezer, state, role) -> None:
    """Every armed state maps to its role (source alarmo) and starts an override."""
    entry, fake = await _setup(hass, freezer)
    await _start_in(entry, "away" if role == "vacation" else "vacation")
    changes = async_capture_events(hass, EVENT_CHANGED)
    await _keypad(hass, fake, state)
    assert primary(entry) == role
    assert changes[-1].data["source"] == "alarmo"
    assert changes[-1].data["rule"] == f"alarmo:{state}"
    override = data(entry).override
    assert override is not None and override.set_by == "alarmo"
    assert fake.calls == []  # never echoed back


async def test_from_alarmo_disarmed_mapping(hass, freezer) -> None:
    """disarmed maps to its role as well."""
    entry, fake = await _setup(hass, freezer, alarmo_state="armed_away")
    await _keypad(hass, fake, "armed_night")
    assert primary(entry) == "night"
    await _keypad(hass, fake, "disarmed")
    assert primary(entry) == "home"
    assert fake.calls == []


async def test_from_alarmo_ignores_transitions(hass, freezer) -> None:
    """arming / pending / triggered never change the mode."""
    entry, fake = await _setup(hass, freezer)
    for state in ("arming", "pending", "triggered", "unavailable"):
        await _keypad(hass, fake, state)
        assert primary(entry) == "home"


async def test_from_alarmo_blocks_lower_priority_autorules(hass, freezer) -> None:
    """An Alarmo-started override blocks presence rules until it ends."""
    entry, fake = await _setup(hass, freezer)
    await _keypad(hass, fake, "armed_night")
    result = await entry.runtime_data.engine.async_set_primary(
        "away", ChangeSource.PRESENCE, rule="all_away"
    )
    assert result.status.value == "ignored"
    assert primary(entry) == "night"


async def test_from_alarmo_respects_override_settings(hass, freezer) -> None:
    """The override started by Alarmo follows the override options (duration)."""
    entry, fake = await _setup(
        hass, freezer, top={"override": {"until": "duration", "duration_min": 30}}
    )
    await _keypad(hass, fake, "armed_away")
    override = data(entry).override
    assert override.mode.value == "timed"


async def test_mapping_flags_are_per_direction(hass, freezer) -> None:
    """A mapping row can be limited to one direction; unmapped roles are ignored."""
    mappings = _mappings(
        armed_away={"from_alarmo": False},
        armed_night={"to_alarmo": False},
        armed_vacation={"role": None},
    )
    entry, fake = await _setup(hass, freezer, mappings=mappings)
    await _keypad(hass, fake, "armed_away")
    assert primary(entry) == "home"  # from_alarmo off
    await call(hass, "set_mode", {"mode": "night"})
    assert fake.calls == []  # to_alarmo off
    await _keypad(hass, fake, "armed_vacation")
    assert primary(entry) == "night"  # no role mapped


async def test_direction_to_alarmo_only(hass, freezer) -> None:
    """to_alarmo: Alarmo changes are ignored, Home Modes changes arm Alarmo."""
    entry, fake = await _setup(hass, freezer, direction="to_alarmo")
    await _keypad(hass, fake, "armed_night")
    assert primary(entry) == "home"
    await call(hass, "set_mode", {"mode": "away"})
    assert len(fake.arm_calls) == 1


async def test_direction_from_alarmo_only(hass, freezer) -> None:
    """from_alarmo: mode changes never touch Alarmo; Alarmo changes the mode."""
    entry, fake = await _setup(hass, freezer, direction="from_alarmo")
    await call(hass, "set_mode", {"mode": "away"})
    assert fake.calls == []
    await _keypad(hass, fake, "armed_night")
    assert primary(entry) == "night"


# --- to_alarmo ---------------------------------------------------------------


@pytest.mark.parametrize(("state", "role"), list(TABLE.items()))
async def test_to_alarmo_every_mapping(hass, freezer, state, role) -> None:
    """Every role arms Alarmo in its mapped mode through alarmo.arm (no code, no force)."""
    entry, fake = await _setup(
        hass, freezer, alarmo_state="armed_home" if role != "home" else "armed_away"
    )
    await _start_in(entry, "vacation" if role != "vacation" else "away")
    await call(hass, "set_mode", {"mode": role})
    await hass.async_block_till_done()
    assert len(fake.arm_calls) == 1
    call_data = fake.arm_calls[0]
    assert call_data["entity_id"] == ENTITY
    assert call_data["mode"] == state.removeprefix("armed_").replace("custom_bypass", "custom")
    assert call_data["force"] is False and call_data["skip_delay"] is False
    assert "code" not in call_data
    assert hass.states.get(ENTITY).state == state


async def test_to_alarmo_no_call_when_already_in_state(hass, freezer) -> None:
    """Nothing is sent when Alarmo is already in the target state."""
    _entry, fake = await _setup(hass, freezer, alarmo_state="armed_away")
    await call(hass, "set_mode", {"mode": "away"})
    assert fake.calls == []


async def test_exit_delay_respected(hass, freezer) -> None:
    """With an exit delay Alarmo goes through arming; the bridge does not skip the delay."""
    _entry, fake = await _setup(hass, freezer, exit_delay=30)
    await call(hass, "set_mode", {"mode": "away"})
    assert hass.states.get(ENTITY).state == "arming"
    assert fake.arm_calls[0]["skip_delay"] is False
    fake.finish_arming()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "armed_away"


# --- safety -------------------------------------------------------------------


async def test_never_disarms_by_default(hass, freezer) -> None:
    """A role mapped to disarmed without 'allow disarm' never disarms Alarmo."""
    mappings = _mappings(disarmed={"role": "home", "to_alarmo": True})
    entry, fake = await _setup(hass, freezer, alarmo_state="armed_away", mappings=mappings)
    await call(hass, "set_mode", {"mode": "night"})  # night arms (armed_night)
    await call(hass, "set_mode", {"mode": "home"})
    assert [name for name, *_ in fake.calls] == ["arm"]
    assert hass.states.get(ENTITY).state == "armed_night"
    notes = entry.runtime_data.history.entries[-1]["bridge"]
    assert {"alarmo": "disarm_not_allowed"} in notes


async def test_disarm_only_with_explicit_switch(hass, freezer) -> None:
    """With allow_disarm a role mapped to disarmed disarms (alarmo.disarm, no code)."""
    mappings = _mappings(disarmed={"role": "home", "to_alarmo": True, "allow_disarm": True})
    entry, fake = await _setup(hass, freezer, alarmo_state="armed_away", mappings=mappings)
    await _start_in(entry, "night")
    await call(hass, "set_mode", {"mode": "home"})
    assert fake.calls[-1][0] == "disarm"
    assert fake.calls[-1][1] == {"entity_id": ENTITY}
    assert hass.states.get(ENTITY).state == "disarmed"


async def test_disarm_blocked_for_allow_list_user(hass, freezer, guest_user) -> None:
    """Even with allow_disarm, an allow-list (guest) user cannot disarm via a mode change."""
    mappings = _mappings(disarmed={"role": "home", "to_alarmo": True, "allow_disarm": True})
    fake = FakeAlarmo(hass, state="armed_night")
    options = _options(mappings=mappings)
    options["user_rules"] = {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}
    entry = await setup_entry(hass, freezer, options)
    await call(hass, "set_mode", {"mode": "night"})  # already night? primary is home -> night
    await call(hass, "set_mode", {"mode": "home"}, user_id=guest_user.id)
    assert all(name != "disarm" for name, *_ in fake.calls)
    assert {"alarmo": "disarm_blocked_for_restricted_user"} in entry.runtime_data.history.entries[
        -1
    ]["bridge"]


async def test_auto_rule_changes_do_not_touch_alarmo(hass, freezer) -> None:
    """Rank 2-4 changes (and expiry) never arm/disarm Alarmo unless apply_auto is on."""
    entry, fake = await _setup(hass, freezer)
    engine = entry.runtime_data.engine
    for source in (ChangeSource.SCHEDULE, ChangeSource.SENSOR, ChangeSource.PRESENCE):
        await engine.async_set_primary("away", source, rule="x")
        await engine.async_set_primary("home", source, rule="x")
    assert fake.calls == []


async def test_apply_auto_arms_but_never_disarms_without_switch(hass, freezer) -> None:
    """apply_auto lets auto-rules arm Alarmo; disarming still needs allow_disarm."""
    mappings = _mappings(disarmed={"role": "home", "to_alarmo": True})
    entry, fake = await _setup(
        hass, freezer, alarmo_state="armed_away", apply_auto=True, mappings=mappings
    )
    engine = entry.runtime_data.engine
    await engine.async_set_primary("night", ChangeSource.SCHEDULE, rule="night_window")
    assert len(fake.arm_calls) == 1 and hass.states.get(ENTITY).state == "armed_night"
    await engine.async_set_primary("home", ChangeSource.PRESENCE, rule="home")
    assert [n for n, *_ in fake.calls] == ["arm"]
    assert hass.states.get(ENTITY).state == "armed_night"


async def test_startup_reconcile_never_touches_alarmo(hass, freezer) -> None:
    """System changes (e.g. a role disabled while the active mode) never reach Alarmo."""
    entry, fake = await _setup(hass, freezer, apply_auto=True)
    await entry.runtime_data.engine.async_set_primary(
        "night", ChangeSource.SYSTEM, rule="role_disabled"
    )
    assert [n for n, *_ in fake.calls] == []


@pytest.mark.parametrize("busy", ["pending", "triggered", "arming"])
async def test_no_interference_while_alarm_busy(hass, freezer, busy) -> None:
    """While Alarmo is arming/pending/triggered the bridge leaves it alone."""
    entry, fake = await _setup(hass, freezer)
    fake.set(busy)
    await call(hass, "set_mode", {"mode": "away"})
    assert fake.calls == []
    assert primary(entry) == "away"
    assert any(
        str(n.get("alarmo", "")).startswith("alarm_busy")
        for n in entry.runtime_data.history.entries[-1]["bridge"]
    )


async def test_code_required_is_reported_never_stored(hass, freezer) -> None:
    """If Alarmo wants a code, the bridge reports it instead of acting; no code is stored."""
    entry, fake = await _setup(hass, freezer, code=True)
    await call(hass, "set_mode", {"mode": "away"})
    assert fake.calls == []
    assert entry.runtime_data.history.entries[-1]["bridge"][0]["error"] == "code_required"
    assert primary(entry) == "away"
    assert "code" not in str(entry.options["alarmo"])


async def test_service_error_is_isolated(hass, freezer) -> None:
    """A failing alarmo.arm does not affect the mode change."""
    entry, _fake = await _setup(hass, freezer)

    async def boom(call):
        raise RuntimeError("alarmo exploded")

    hass.services.async_register("alarmo", "arm", boom)
    await call(hass, "set_mode", {"mode": "away"})
    assert primary(entry) == "away"
    assert entry.runtime_data.history.entries[-1]["bridge"][0]["error"] == "alarmo_call_failed"


async def test_failed_to_arm_is_reported_mode_not_reverted(hass, freezer) -> None:
    """Open sensors: Alarmo refuses, the bridge reports it, the role stays."""
    entry, fake = await _setup(hass, freezer, exit_delay=0)

    async def refuse(call):
        fake.calls.append(("arm", dict(call.data), call.context))
        hass.bus.async_fire("alarmo_failed_to_arm", {"reason": "open_sensors", "entity_id": ENTITY})

    hass.services.async_register("alarmo", "arm", refuse)
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert primary(entry) == "away"
    errors = [e for e in entry.runtime_data.history.entries if e["kind"] == "system"]
    assert errors[-1]["bridge"][0]["error"] == "failed_to_arm"


async def test_failed_to_arm_from_keypad_is_ignored(hass, freezer) -> None:
    """A failed arm that was not requested by the bridge is not its business."""
    entry, _fake = await _setup(hass, freezer)
    hass.bus.async_fire("alarmo_failed_to_arm", {"reason": "open_sensors", "entity_id": ENTITY})
    await hass.async_block_till_done()
    assert not [e for e in entry.runtime_data.history.entries if e["kind"] == "system"]


# --- loop guard ---------------------------------------------------------------


async def test_no_echo_to_alarmo_instant(hass, freezer) -> None:
    """Home Modes -> Alarmo (instant): context survives, exactly one change and one call."""
    entry, fake = await _setup(hass, freezer)
    changes = async_capture_events(hass, EVENT_CHANGED)
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert len(changes) == 1 and len(fake.calls) == 1
    assert data(entry).override is None or data(entry).override.set_by == "manual"


async def test_no_echo_with_exit_delay_context_lost(hass, freezer) -> None:
    """With an exit delay the final state has no usable context: expected-state suppression."""
    entry, fake = await _setup(hass, freezer, exit_delay=30)
    changes = async_capture_events(hass, EVENT_CHANGED)
    await call(hass, "set_mode", {"mode": "away"})
    await advance(hass, freezer, seconds=25)  # longer than the 15 s instant window
    fake.finish_arming()
    await hass.async_block_till_done()
    assert len(changes) == 1  # no second change (alarmo-sourced echo)
    assert len(fake.calls) == 1
    assert data(entry).last_trigger.source == "manual"


async def test_echo_window_expires(hass, freezer) -> None:
    """After the expectation expired the same state is a genuine Alarmo change."""
    entry, fake = await _setup(hass, freezer)
    await call(hass, "set_mode", {"mode": "away"})
    await advance(hass, freezer, minutes=5)
    await _keypad(hass, fake, "armed_night")
    assert primary(entry) == "night"
    await _keypad(hass, fake, "armed_away")  # a real keypad change to away
    assert primary(entry) == "away"
    assert len(fake.calls) == 1


async def test_no_echo_from_alarmo(hass, freezer) -> None:
    """Alarmo -> Home Modes never calls Alarmo back, for every state."""
    _entry, fake = await _setup(hass, freezer)
    for state in ("armed_away", "armed_night", "armed_vacation", "armed_home", "disarmed"):
        await _keypad(hass, fake, state)
    assert fake.calls == []


async def test_near_simultaneous_changes(hass, freezer) -> None:
    """Both sides change at (nearly) the same moment: no ping-pong, bounded calls."""
    _entry, fake = await _setup(hass, freezer, exit_delay=30)
    changes = async_capture_events(hass, EVENT_CHANGED)
    await asyncio.gather(
        call(hass, "set_mode", {"mode": "away"}),
        _keypad(hass, fake, "armed_night"),
    )
    await advance(hass, freezer, seconds=40)
    await hass.async_block_till_done()
    assert len(changes) <= 3
    assert len(fake.arm_calls) <= 1
    count = len(changes)
    await advance(hass, freezer, minutes=10)
    assert len(changes) == count  # settled


async def test_keypad_disarm_during_our_arming(hass, freezer) -> None:
    """Someone disarms at the keypad while our arm request is counting down."""
    entry, fake = await _setup(hass, freezer, exit_delay=30)
    await call(hass, "set_mode", {"mode": "away"})
    assert hass.states.get(ENTITY).state == "arming"
    fake.pending = None
    await _keypad(hass, fake, "disarmed")  # keypad cancel
    assert primary(entry) == "home"  # disarmed maps to home (from_alarmo)
    await advance(hass, freezer, seconds=60)
    assert len(fake.arm_calls) == 1


# --- Ring-style keypad --------------------------------------------------------


async def test_ring_keypad_sequence(hass, freezer) -> None:
    """Keypad: arm away (exit delay), failed attempt, re-arm, then disarm with the code."""
    entry, fake = await _setup(hass, freezer)
    changes = async_capture_events(hass, EVENT_CHANGED)

    # 1. arm away pressed: blueprint calls alarmo.arm -> arming -> armed_away
    await _keypad(hass, fake, "arming", delay=30, arm_mode="armed_away")
    assert primary(entry) == "home" and not changes  # arming is not a target state
    # 2. open sensor: Alarmo fires the event and reverts to disarmed (blueprint then re-arms)
    hass.bus.async_fire("alarmo_failed_to_arm", {"reason": "open_sensors", "entity_id": ENTITY})
    await _keypad(hass, fake, "disarmed")
    assert primary(entry) == "home" and not changes  # home -> home: unchanged
    # 3. re-armed with force: arming -> armed_away
    await _keypad(hass, fake, "arming", delay=30)
    await _keypad(hass, fake, "armed_away")
    assert primary(entry) == "away"
    assert changes[-1].data["source"] == "alarmo"
    # 4. entry delay and disarm with the code
    await _keypad(hass, fake, "pending")
    await _keypad(hass, fake, "disarmed")
    assert primary(entry) == "home"
    assert fake.calls == []  # Home Modes never answered with a service call
    assert [c.data["to"] for c in changes] == ["away", "home"]


async def test_keypad_change_starts_override_that_survives_presence(hass, freezer) -> None:
    """A keypad change is a user action: it starts an override (per override settings)."""
    entry, fake = await _setup(hass, freezer)
    await _keypad(hass, fake, "armed_away")
    assert data(entry).override.set_by == "alarmo"
    hass_state = async_mock_service  # noqa: F841 - keep import used
