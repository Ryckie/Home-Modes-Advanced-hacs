"""Options flow screens of Step 4 and settings parsing."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.home_modes.models import Role
from custom_components.home_modes.settings import parse_integration_settings

from .helpers import setup_entry


async def _menu(hass: HomeAssistant, flow_id: str, step: str):
    return await hass.config_entries.options.async_configure(flow_id, {"next_step_id": step})


async def _form(hass: HomeAssistant, flow_id: str, payload: dict):
    return await hass.config_entries.options.async_configure(flow_id, payload)


async def _open(hass: HomeAssistant, entry, step: str):
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    await _menu(hass, flow_id, "integrations")
    result = await _menu(hass, flow_id, step)
    return flow_id, result


async def _save(hass: HomeAssistant, flow_id: str) -> None:
    await _menu(hass, flow_id, "init")
    result = await _menu(hass, flow_id, "save")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_menu_stays_readable(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The top menu gets one new entry; the integrations are in a sub-menu."""
    entry = await setup_entry(hass, freezer)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert "integrations" in result["menu_options"]
    assert len(result["menu_options"]) <= 11
    result = await _menu(hass, result["flow_id"], "integrations")
    assert result["menu_options"] == [
        "actions",
        "alarmo",
        "vacation",
        "notify",
        "history",
        "import_input_select",
        "init",
    ]


async def test_actions_screen(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Actions are stored per role (also overlays) and the timeout is saved."""
    entry = await setup_entry(hass, freezer)
    flow_id, result = await _open(hass, entry, "actions")
    result = await _form(hass, flow_id, {"role": "guest", "actions_timeout_s": 12})
    assert result["step_id"] == "actions_edit"
    result = await _form(
        hass,
        flow_id,
        {
            "enter_actions": [{"action": "light.turn_on", "target": {"entity_id": "light.x"}}],
            "exit_actions": [{"delay": {"seconds": 1}}],
        },
    )
    assert result["step_id"] == "integrations"
    await _save(hass, flow_id)
    runtime = entry.runtime_data
    guest = runtime.coordinator.role("guest")
    assert guest.enter_actions[0]["action"] == "light.turn_on"
    assert guest.exit_actions == ({"delay": {"seconds": 1}},)
    assert runtime.coordinator.integrations.actions_timeout == 12


async def test_actions_validation(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Invalid action sequences are rejected."""
    entry = await setup_entry(hass, freezer)
    flow_id, _ = await _open(hass, entry, "actions")
    await _form(hass, flow_id, {"role": "home", "actions_timeout_s": 30})
    result = await _form(hass, flow_id, {"enter_actions": [{"nonsense": 1}]})
    assert result["errors"] == {"enter_actions": "invalid_actions"}


async def test_rename_keeps_actions(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Renaming or disabling a role does not drop its actions."""
    roles = [
        {**r, "enter_actions": [{"delay": {"seconds": 1}}]} if r["id"] == "night" else r
        for r in (await setup_entry(hass, freezer)).options["roles"]
    ]
    assert Role.from_dict(roles[1]).enter_actions
    entry = await setup_entry(hass, freezer, {"roles": roles})
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    await _menu(hass, flow_id, "edit_role")
    await _form(hass, flow_id, {"role": "night"})
    await _form(hass, flow_id, {"name": "Sleep", "enabled": True})
    await _menu(hass, flow_id, "save")
    await hass.async_block_till_done()
    night = entry.runtime_data.coordinator.role("night")
    assert night.name == "Sleep" and night.enter_actions


async def _map_all(hass, flow_id, rows: dict[str, dict]):
    result = None
    for state in (
        "disarmed",
        "armed_home",
        "armed_away",
        "armed_night",
        "armed_vacation",
        "armed_custom_bypass",
    ):
        row = {"to_alarmo": False, "from_alarmo": False, **rows.get(state, {})}
        if state == "disarmed":
            row.setdefault("allow_disarm", False)
        result = await _form(hass, flow_id, row)
    return result


async def test_alarmo_screen_and_defaults(hass: HomeAssistant, freezer) -> None:
    """The Alarmo screens save the mapping; allow_disarm is off unless switched on."""
    entry = await setup_entry(hass, freezer)
    assert parse_integration_settings(entry.options).alarmo.enabled is False
    flow_id, result = await _open(hass, entry, "alarmo")
    result = await _form(
        hass,
        flow_id,
        {"enabled": True, "direction": "both", "apply_auto": False},
    )
    assert result["step_id"] == "alarmo_map_disarmed"
    result = await _map_all(
        hass,
        flow_id,
        {
            "disarmed": {"role": "home", "from_alarmo": True},
            "armed_away": {"role": "away", "to_alarmo": True, "from_alarmo": True},
            "armed_night": {"role": "night", "to_alarmo": True},
        },
    )
    assert result["step_id"] == "integrations"
    await _save(hass, flow_id)
    cfg = entry.runtime_data.coordinator.integrations.alarmo
    assert cfg.enabled and cfg.direction == "both" and cfg.apply_auto is False
    rows = {m.state: m for m in cfg.mappings}
    assert len(rows) == 6
    assert rows["disarmed"].allow_disarm is False
    assert rows["armed_away"].to_alarmo and rows["armed_away"].from_alarmo
    assert rows["armed_night"].to_alarmo and not rows["armed_night"].from_alarmo


async def test_alarmo_allow_disarm_needs_to_alarmo(hass: HomeAssistant, freezer) -> None:
    """allow_disarm is only kept when the disarmed row maps in the to_alarmo direction."""
    entry = await setup_entry(hass, freezer)
    flow_id, _ = await _open(hass, entry, "alarmo")
    await _form(hass, flow_id, {"enabled": True, "direction": "both", "apply_auto": False})
    await _map_all(
        hass,
        flow_id,
        {"disarmed": {"role": "home", "from_alarmo": True, "allow_disarm": True}},
    )
    await _save(hass, flow_id)
    row = next(
        m
        for m in entry.runtime_data.coordinator.integrations.alarmo.mappings
        if m.state == "disarmed"
    )
    assert row.allow_disarm is False


async def test_alarmo_validation(hass: HomeAssistant, freezer) -> None:
    """A role is required for enabled rows; a role maps to one Alarmo state when sending."""
    entry = await setup_entry(hass, freezer)
    flow_id, _ = await _open(hass, entry, "alarmo")
    await _form(hass, flow_id, {"enabled": True, "direction": "both", "apply_auto": False})
    result = await _form(
        hass, flow_id, {"to_alarmo": True, "from_alarmo": False, "allow_disarm": False}
    )
    assert result["errors"] == {"role": "role_required"}
    await _form(
        hass,
        flow_id,
        {"role": "home", "to_alarmo": True, "from_alarmo": False, "allow_disarm": False},
    )
    result = await _form(hass, flow_id, {"role": "home", "to_alarmo": True, "from_alarmo": False})
    assert result["errors"] == {"role": "duplicate_role"}


async def test_alarmo_disabled_keeps_mappings(hass: HomeAssistant, freezer) -> None:
    """Switching the bridge off does not throw the mapping table away."""
    options = {
        "alarmo": {
            "enabled": True,
            "mappings": [{"state": "armed_away", "role": "away", "to_alarmo": True}],
        }
    }
    entry = await setup_entry(hass, freezer, options)
    flow_id, _ = await _open(hass, entry, "alarmo")
    result = await _form(
        hass, flow_id, {"enabled": False, "direction": "both", "apply_auto": False}
    )
    assert result["step_id"] == "integrations"
    await _save(hass, flow_id)
    cfg = entry.runtime_data.coordinator.integrations.alarmo
    assert not cfg.enabled and cfg.mappings[0].role == "away"


VAC = {
    "enabled": True,
    "roles": ["vacation"],
    "strategy": "replay",
    "lights": ["light.a"],
    "start": "18:00:00",
    "end": "23:00:00",
    "min_on_min": 10,
    "max_on_min": 30,
    "min_gap_min": 5,
}


async def test_vacation_screen(hass: HomeAssistant, freezer) -> None:
    """The vacation screen saves and validates every field."""
    entry = await setup_entry(hass, freezer)
    flow_id, _ = await _open(hass, entry, "vacation")
    for bad, error in (
        ({"lights": []}, {"lights": "lights_required"}),
        ({"roles": []}, {"roles": "roles_required"}),
        ({"end": "17:00:00"}, {"end": "window_same_day"}),
        ({"min_on_min": 50}, {"max_on_min": "max_before_min"}),
    ):
        result = await _form(hass, flow_id, {**VAC, **bad})
        assert result["errors"] == error
    result = await _form(hass, flow_id, VAC)
    assert result["step_id"] == "integrations"
    await _save(hass, flow_id)
    cfg = entry.runtime_data.coordinator.integrations.vacation
    assert cfg.enabled and cfg.strategy == "replay" and cfg.lights == ("light.a",)
    assert cfg.min_on == timedelta(minutes=10) and cfg.min_gap == timedelta(minutes=5)


async def test_notify_screens(hass: HomeAssistant, freezer) -> None:
    """Rules can be added (validated), listed, removed; the rate limit is configurable."""
    entry = await setup_entry(hass, freezer)
    flow_id, result = await _open(hass, entry, "notify")
    assert result["menu_options"] == ["notify_add", "notify_settings", "integrations"]
    await _menu(hass, flow_id, "notify_add")
    result = await _form(hass, flow_id, {"event": "any_change"})
    assert result["errors"] == {"targets": "no_target"}
    result = await _form(
        hass,
        flow_id,
        {"event": "changed_to", "services": ["mobile_app_x"], "message": "{{ to_mode"},
    )
    assert result["errors"] == {"role": "role_required", "message": "template_invalid"}
    result = await _form(
        hass,
        flow_id,
        {
            "event": "changed_to",
            "role": "away",
            "services": ["mobile_app_x"],
            "targets": ["notify.phone"],
            "message": "{{ to_mode }} at {{ time }}",
        },
    )
    assert result["type"] is FlowResultType.MENU
    assert "notify_remove" in result["menu_options"]
    await _menu(hass, flow_id, "notify_add")
    await _form(hass, flow_id, {"event": "denied", "services": ["mobile_app_x"]})
    await _menu(hass, flow_id, "notify_settings")
    await _form(hass, flow_id, {"rate_limit_s": 30})
    await _menu(hass, flow_id, "notify_remove")
    result = await _form(hass, flow_id, {"rule": "1"})
    await _menu(hass, flow_id, "integrations")
    await _save(hass, flow_id)
    notify = entry.runtime_data.coordinator.integrations.notify
    assert [r.event for r in notify.rules] == ["changed_to"]
    assert notify.rules[0].role == "away" and notify.rules[0].targets == ("notify.phone",)
    assert notify.rate_limit == timedelta(seconds=30)


async def test_history_screen_and_parsing_defaults(hass: HomeAssistant, freezer) -> None:
    """History size is configurable; garbage options fall back to safe defaults."""
    entry = await setup_entry(hass, freezer)
    assert entry.runtime_data.coordinator.integrations.history_max == 500
    flow_id, _ = await _open(hass, entry, "history")
    await _form(hass, flow_id, {"max_entries": 120})
    await _save(hass, flow_id)
    assert entry.runtime_data.coordinator.integrations.history_max == 120
    bad = parse_integration_settings(
        {
            "alarmo": {
                "enabled": "yes",
                "direction": "sideways",
                "mappings": ["x", {"state": "zzz"}],
            },
            "vacation_sim": {"strategy": "magic", "start": "bad", "min_on_min": "x"},
            "notify": {"rules": [{"event": "nope"}], "rate_limit_s": -5},
            "history": {"max_entries": 99999},
            "actions_timeout_s": 0,
        }
    )
    assert bad.alarmo.enabled is False and bad.alarmo.direction == "both"
    assert bad.alarmo.mappings == ()
    assert bad.vacation.strategy == "random" and bad.vacation.min_on == timedelta(minutes=20)
    assert bad.notify.rules == () and bad.notify.rate_limit == timedelta(0)
    assert bad.history_max == 5000 and bad.actions_timeout == 1.0


def test_disarm_screen_carries_a_warning() -> None:
    """The disarm mapping screen warns, in the options text, that it disarms the alarm."""
    import json
    from pathlib import Path

    texts = json.loads(
        (
            Path(__file__).parents[1] / "custom_components/home_modes/translations/en.json"
        ).read_text()
    )["options"]["step"]
    assert texts["alarmo_map_disarmed"]["description"].startswith("WARNING")
    assert "DISARM" in texts["alarmo_map_disarmed"]["description"]
    assert "dangerous" in texts["alarmo_map_disarmed"]["data"]["allow_disarm"]
    assert "No alarm code is ever stored" in texts["alarmo"]["description"]
