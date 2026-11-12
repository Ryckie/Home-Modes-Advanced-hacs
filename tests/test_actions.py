"""Enter/exit actions: order, context, timeout, failure isolation, loop protection."""

from __future__ import annotations

import asyncio

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant, ServiceCall, callback
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.home_modes.const import DOMAIN, EVENT_CHANGED

from .conftest import make_entry
from .helpers import call, primary, roles_without, setup_entry


def _roles(**actions: dict) -> list[dict]:
    roles = roles_without()
    for role in roles:
        if role["id"] in actions:
            role.update(actions[role["id"]])
    return roles


def _event(name: str, **data: str) -> dict:
    return {"event": name, "event_data": data}


async def test_exit_before_state_enter_after(hass: HomeAssistant, freezer) -> None:
    """Exit actions run before the state changes, enter actions after (then the event)."""
    order: list[str] = []

    @callback
    def record(event) -> None:
        order.append(f"{event.event_type}:{hass.states.get('select.home_mode').state}")

    for name in ("hm_exit", "hm_enter", EVENT_CHANGED):
        hass.bus.async_listen(name, record)
    roles = _roles(
        home={"exit_actions": [_event("hm_exit")]},
        away={"enter_actions": [_event("hm_enter")]},
    )
    entry = await setup_entry(hass, freezer, {"roles": roles})
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert order == ["hm_exit:Home", "hm_enter:Away", f"{EVENT_CHANGED}:Away"]
    assert primary(entry) == "away"


async def test_overlay_actions_and_custom_modes(hass: HomeAssistant, freezer) -> None:
    """Overlays and custom modes have actions too (enter on, exit off)."""
    seen = async_capture_events(hass, "hm_x")
    roles = _roles(
        guest={
            "enter_actions": [_event("hm_x", what="guest_on")],
            "exit_actions": [_event("hm_x", what="guest_off")],
        },
    )
    roles.append(
        {
            "id": "custom_1",
            "name": "Party",
            "enabled": True,
            "enter_actions": [_event("hm_x", what="party")],
        }
    )
    await setup_entry(hass, freezer, {"roles": roles})
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await call(hass, "set_mode", {"mode": "custom_1"})
    await hass.async_block_till_done()
    assert [e.data["what"] for e in seen] == ["guest_on", "guest_off", "party"]


async def test_action_context_is_child_of_change_context(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Actions run with a context whose parent_id is the change's context."""
    seen = async_capture_events(hass, "hm_ctx")
    roles = _roles(away={"enter_actions": [_event("hm_ctx")]})
    await setup_entry(hass, freezer, {"roles": roles})
    parent = Context()
    await hass.services.async_call(
        DOMAIN, "set_mode", {"mode": "away"}, blocking=True, context=parent
    )
    await hass.async_block_till_done()
    assert len(seen) == 1
    assert seen[0].context.parent_id == parent.id
    assert seen[0].context.id != parent.id


async def test_action_variables(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Actions can use from, to, role, phase, source, rule."""
    seen = async_capture_events(hass, "hm_vars")
    roles = _roles(
        away={
            "enter_actions": [
                {
                    "event": "hm_vars",
                    "event_data": {
                        "v": (
                            "{{ from_role }}>{{ to_role }}:{{ from_name }}>{{ to_name }}"
                            ":{{ role }}:{{ phase }}:{{ source }}"
                        )
                    },
                }
            ]
        }
    )
    await setup_entry(hass, freezer, {"roles": roles})
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert seen[0].data["v"] == "home>away:Home>Away:away:enter:manual"


async def test_failing_action_is_isolated_and_reported(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A failing action never blocks the change; later actions still run; history shows it."""
    seen = async_capture_events(hass, "hm_after")
    roles = _roles(
        away={
            "enter_actions": [
                {"action": "no_such.service"},
                _event("hm_after"),
            ]
        }
    )
    entry = await setup_entry(hass, freezer, {"roles": roles})
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert primary(entry) == "away"
    assert len(seen) == 1
    last = entry.runtime_data.history.entries[-1]
    assert last["to"] == "away"
    failures = last["action_failures"]
    assert len(failures) == 1
    assert failures[0]["phase"] == "enter" and failures[0]["index"] == 1


async def test_failing_exit_action_does_not_block(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A failing exit action does not stop the change either."""
    roles = _roles(home={"exit_actions": [{"action": "no_such.service"}]})
    entry = await setup_entry(hass, freezer, {"roles": roles})
    await call(hass, "set_mode", {"mode": "night"})
    assert primary(entry) == "night"
    assert entry.runtime_data.history.entries[-1]["action_failures"][0]["phase"] == "exit"


async def test_action_timeout(hass: HomeAssistant) -> None:
    """A slow action is stopped after the timeout and reported; the change still happens."""
    started = asyncio.Event()

    async def slow(call: ServiceCall) -> None:
        started.set()
        await asyncio.sleep(3600)

    hass.services.async_register("test", "slow", slow)
    roles = _roles(away={"enter_actions": [{"action": "test.slow"}]})
    # no frozen clock here: asyncio.timeout needs the real event loop time
    entry = make_entry(options={"roles": roles, "actions_timeout_s": 1})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await call(hass, "set_mode", {"mode": "away"})
    assert started.is_set()
    assert primary(entry) == "away"
    failure = entry.runtime_data.history.entries[-1]["action_failures"][0]
    assert "timeout" in failure["error"]


async def test_action_changing_mode_is_deferred_and_loop_limited(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An action that sets the mode again is applied afterwards; endless ping-pong stops."""
    roles = _roles(
        home={"enter_actions": [{"action": "home_modes.set_mode", "data": {"mode": "away"}}]},
        away={"enter_actions": [{"action": "home_modes.set_mode", "data": {"mode": "home"}}]},
    )
    entry = await setup_entry(hass, freezer, {"roles": roles})
    changes = async_capture_events(hass, EVENT_CHANGED)
    await call(
        hass, "set_mode", {"mode": "away"}
    )  # away -> action sets home -> action sets away ...
    await hass.async_block_till_done()
    # initial change + at most ACTION_LOOP_MAX (3) action-triggered ones
    assert 2 <= len(changes) <= 4
    systems = [e for e in entry.runtime_data.history.entries if e["rule"] == "action_loop_blocked"]
    assert len(systems) == 1
