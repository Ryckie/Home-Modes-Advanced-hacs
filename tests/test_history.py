"""History log, logbook descriptions, clear_history service and websocket command."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from custom_components.home_modes import logbook
from custom_components.home_modes.const import DOMAIN, EVENT_CHANGED, EVENT_DENIED

from .helpers import advance, call, reload, setup_entry

CLIENT_ID = "https://example.com/app"


async def _client(hass: HomeAssistant, hass_ws_client, user):
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    token = hass.auth.async_create_access_token(refresh)
    return await hass_ws_client(hass, token)


async def test_entries_record_changes_overlays_denied(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """Primary, overlay, denied and system entries have the documented fields."""
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    await call(hass, "set_mode", {"mode": "night"})
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    with pytest.raises(Exception):  # noqa: B017 - denied for the guest
        await call(hass, "set_mode", {"mode": "away"}, user_id=guest_user.id)
    await hass.async_block_till_done()
    kinds = [e["kind"] for e in entry.runtime_data.history.entries]
    assert kinds == ["primary", "overlay", "denied"]
    primary_entry, overlay_entry, denied_entry = entry.runtime_data.history.entries
    for key in (
        "ts",
        "kind",
        "from",
        "to",
        "role",
        "source",
        "rule",
        "user_id",
        "user",
        "action_failures",
        "bridge",
    ):
        assert key in primary_entry
    assert (primary_entry["from"], primary_entry["to"], primary_entry["source"]) == (
        "home",
        "night",
        "manual",
    )
    assert overlay_entry["to"] == "guest" and overlay_entry["role"] == "guest"
    assert denied_entry["user"] == "Guest" and denied_entry["rule"] == "not_in_allow_list"
    entry.runtime_data.engine.system_log("vacation_sim_start", {"x": 1})
    assert entry.runtime_data.history.entries[-1]["kind"] == "system"


async def test_cap_default_and_configurable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The log keeps only the newest N entries (configurable, default 500)."""
    entry = await setup_entry(hass, freezer, {"history": {"max_entries": 10}})
    assert entry.runtime_data.coordinator.integrations.history_max == 10
    for index in range(15):
        await call(hass, "set_mode", {"mode": "night" if index % 2 == 0 else "away"})
    entries = entry.runtime_data.history.entries
    assert len(entries) == 10
    assert entries[-1]["to"] == "night"
    default = await setup_default_cap(hass)
    assert default == 500


async def setup_default_cap(hass: HomeAssistant) -> int:
    from custom_components.home_modes.settings import parse_integration_settings

    return parse_integration_settings({}).history_max


async def test_persisted_across_restart_with_delayed_save(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage
) -> None:
    """Entries use a delayed save and survive a reload."""
    entry = await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "night"})
    key = f"{DOMAIN}.{entry.entry_id}.history"
    assert key not in hass_storage  # delayed: not written yet
    await advance(hass, freezer, seconds=2)
    assert len(hass_storage[key]["data"]["entries"]) == 1
    await call(hass, "set_mode", {"mode": "away"})
    await reload(hass, entry)  # unload writes immediately
    assert [e["to"] for e in entry.runtime_data.history.entries] == ["night", "away"]


async def test_logbook_descriptions(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """home_modes_changed and home_modes_denied are described for the logbook."""
    await setup_entry(hass, freezer)
    described: dict[str, object] = {}
    logbook.async_describe_events(
        hass, lambda domain, event, func: described.__setitem__(event, func)
    )
    assert set(described) == {EVENT_CHANGED, EVENT_DENIED}
    changed = described[EVENT_CHANGED](
        SimpleNamespace(
            data={
                "kind": "primary",
                "from": "home",
                "to": "night",
                "role": "night",
                "source": "schedule",
                "rule": "night_window",
            }
        )
    )
    assert changed["name"] == "Home Modes"
    assert changed["message"] == "changed from Home to Night (source: schedule, rule: night_window)"
    assert changed["entity_id"] == "select.home_mode"
    overlay = described[EVENT_CHANGED](
        SimpleNamespace(
            data={"kind": "overlay", "role": "guest", "active": True, "source": "manual"}
        )
    )
    assert overlay["message"].startswith("Guest turned on")
    denied = described[EVENT_DENIED](
        SimpleNamespace(data={"role": "away", "reason": "not_in_allow_list"})
    )
    assert denied["message"] == "denied change of Away (reason: not_in_allow_list)"


async def test_clear_history_admin_only(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user, guest_user
) -> None:
    """clear_history works for admins and is refused for other users."""
    entry = await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "night"})
    assert entry.runtime_data.history.entries
    with pytest.raises(Unauthorized):
        await call(hass, "clear_history", user_id=guest_user.id)
    assert entry.runtime_data.history.entries
    await call(hass, "clear_history", user_id=hass_admin_user.id)
    assert entry.runtime_data.history.entries == []
    await call(hass, "set_mode", {"mode": "away"})
    await call(hass, "clear_history")  # no user (automation/script) is trusted
    assert entry.runtime_data.history.entries == []


async def test_websocket_permissions(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_ws_client, hass_admin_user, guest_user
) -> None:
    """Admins see everything, normal users mode changes only, guests nothing."""
    other = await hass.auth.async_create_user("Other", group_ids=[GROUP_ID_USER])
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    await call(hass, "set_mode", {"mode": "night"})
    entry.runtime_data.engine.system_log("vacation_sim_start", {"strategy": "random"})
    entry.runtime_data.history.entries[0]["action_failures"] = [{"error": "x"}]

    admin_ws = await _client(hass, hass_ws_client, hass_admin_user)
    await admin_ws.send_json({"id": 1, "type": "home_modes/history", "limit": 10})
    result = (await admin_ws.receive_json())["result"]["entries"]
    assert [e["kind"] for e in result] == ["system", "primary"]  # newest first
    assert result[1]["action_failures"] == [{"error": "x"}]

    user_ws = await _client(hass, hass_ws_client, other)
    await user_ws.send_json({"id": 1, "type": "home_modes/history", "limit": 10})
    result = (await user_ws.receive_json())["result"]["entries"]
    assert [e["kind"] for e in result] == ["primary"]
    assert result[0]["action_failures"] == [] and result[0]["bridge"] == []

    guest_ws = await _client(hass, hass_ws_client, guest_user)
    await guest_ws.send_json({"id": 1, "type": "home_modes/history"})
    assert (await guest_ws.receive_json())["result"]["entries"] == []

    await admin_ws.send_json({"id": 2, "type": "home_modes/history", "limit": 0})
    assert (await admin_ws.receive_json())["success"] is False  # limit validated
    await admin_ws.send_json({"id": 3, "type": "home_modes/history", "limit": 1})
    assert len((await admin_ws.receive_json())["result"]["entries"]) == 1


async def test_websocket_without_loaded_entry(hass: HomeAssistant, hass_ws_client) -> None:
    """The command reports an error when the integration is not loaded."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "home_modes/history"})
    assert (await client.receive_json())["success"] is False
