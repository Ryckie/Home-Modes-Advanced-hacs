"""Tests for the config and options flows."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.home_modes.const import CONF_PRESET, CONF_ROLES, DOMAIN

from .helpers import options_menu


def _enabled(options: dict) -> dict[str, bool]:
    return {r["id"]: r["enabled"] for r in options[CONF_ROLES]}


async def test_user_flow_simple_and_extended(hass: HomeAssistant) -> None:
    """Both presets create an entry with the right roles enabled."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRESET: "simple"}
    )
    assert result["step_id"] == "people"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "schedule"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data == {CONF_PRESET: "simple"}
    assert [k for k, v in _enabled(entry.options).items() if v] == [
        "home",
        "night",
        "away",
        "vacation",
    ]
    assert hass.states.get("select.home_mode").attributes["options"] == [
        "Home",
        "Night",
        "Away",
        "Vacation",
    ]
    assert hass.states.get("binary_sensor.home_mode_guest") is None
    await hass.config_entries.async_remove(entry.entry_id)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRESET: "extended"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert [k for k, v in _enabled(entry.options).items() if v] == [
        "home",
        "night",
        "away",
        "vacation",
        "all_home",
        "all_away",
        "guest",
        "dnd",
    ]


async def _menu(hass: HomeAssistant, flow_id: str, step: str):
    return await options_menu(hass, flow_id, step)


async def test_options_menu_and_rename_toggle(hass: HomeAssistant, entry) -> None:
    """Renaming and toggling a role saves and reloads the entry."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "modes",
        "automation",
        "user_rules",
        "notify",
        "integrations",
        "save",
    ]
    assert "**Presence:** not set up" in result["description_placeholders"]["summary"]
    flow_id = result["flow_id"]

    result = await _menu(hass, flow_id, "edit_role")
    result = await hass.config_entries.options.async_configure(flow_id, {"role": "night"})
    assert result["step_id"] == "edit_details"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"name": "Sleep", "enabled": True}
    )
    assert result["type"] is FlowResultType.MENU

    result = await _menu(hass, flow_id, "edit_role")
    await hass.config_entries.options.async_configure(flow_id, {"role": "vacation"})
    await hass.config_entries.options.async_configure(
        flow_id, {"name": "Vacation", "enabled": False}
    )

    result = await _menu(hass, flow_id, "save")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    roles = {r["id"]: r for r in entry.options[CONF_ROLES]}
    assert roles["night"]["name"] == "Sleep"
    assert roles["vacation"]["enabled"] is False
    assert hass.states.get("select.home_mode").attributes["options"] == ["Home", "Sleep", "Away"]


async def test_options_validation_errors(hass: HomeAssistant, entry) -> None:
    """Duplicate names, empty names and disabling the last primary are rejected."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]

    async def edit(role: str, name: str, enabled: bool):
        await _menu(hass, flow_id, "edit_role")
        await hass.config_entries.options.async_configure(flow_id, {"role": role})
        return await hass.config_entries.options.async_configure(
            flow_id, {"name": name, "enabled": enabled}
        )

    assert (await edit("night", "away", True))["errors"] == {"base": "name_exists"}
    # The form stays open; go back through the menu by finishing it with a valid edit.
    result = await hass.config_entries.options.async_configure(
        flow_id, {"name": "Night", "enabled": True}
    )
    assert result["type"] is FlowResultType.MENU
    result = await _menu(hass, flow_id, "edit_role")
    await hass.config_entries.options.async_configure(flow_id, {"role": "night"})
    result = await hass.config_entries.options.async_configure(
        flow_id, {"name": "  ", "enabled": True}
    )
    assert result["errors"] == {"base": "name_required"}
    await hass.config_entries.options.async_configure(flow_id, {"name": "Night", "enabled": True})

    for role in ("night", "away", "vacation"):
        await _menu(hass, flow_id, "edit_role")
        await hass.config_entries.options.async_configure(flow_id, {"role": role})
        result = await hass.config_entries.options.async_configure(
            flow_id, {"name": role.title(), "enabled": False}
        )
        assert result["type"] is FlowResultType.MENU
    await _menu(hass, flow_id, "edit_role")
    await hass.config_entries.options.async_configure(flow_id, {"role": "home"})
    result = await hass.config_entries.options.async_configure(
        flow_id, {"name": "Home", "enabled": False}
    )
    assert result["errors"] == {"base": "no_primary"}


async def test_options_move_role(hass: HomeAssistant, entry) -> None:
    """Roles can be moved up and down; moving past the ends does nothing."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    for role, direction in (
        ("night", "up"),
        ("vacation", "down"),
        ("night", "up"),
        ("dnd", "down"),
    ):
        await _menu(hass, flow_id, "move_role")
        result = await hass.config_entries.options.async_configure(
            flow_id, {"role": role, "direction": direction}
        )
        assert result["type"] is FlowResultType.MENU
    await _menu(hass, flow_id, "save")
    await hass.async_block_till_done()
    order = [r["id"] for r in entry.options[CONF_ROLES]]
    assert order[:2] == ["night", "home"]
    assert order.index("vacation") == 4
    assert hass.states.get("select.home_mode").attributes["options"] == [
        "Night",
        "Home",
        "Away",
        "Vacation",
    ]


async def test_options_custom_modes(hass: HomeAssistant, entry) -> None:
    """Custom modes get stable ids, up to ten, and can be removed."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]

    async def add(name: str):
        await _menu(hass, flow_id, "add_custom")
        return await hass.config_entries.options.async_configure(flow_id, {"name": name})

    assert (await add("Cinema"))["type"] is FlowResultType.MENU
    assert (await add("cinema"))["errors"] == {"base": "name_exists"}
    result = await hass.config_entries.options.async_configure(flow_id, {"name": "Reading"})
    assert result["type"] is FlowResultType.MENU
    for n in range(3, 11):
        await add(f"Mode {n}")

    step = await options_menu(hass, flow_id, "remove_custom")
    assert step["step_id"] == "remove_custom"
    result = await hass.config_entries.options.async_configure(flow_id, {"role": "custom_2"})
    assert result["type"] is FlowResultType.MENU
    assert "add_custom" in result["menu_options"]
    assert "remove_custom" in result["menu_options"]

    # The freed id is reused for the next custom mode.
    await add("Gaming")
    await _menu(hass, flow_id, "save")
    await hass.async_block_till_done()
    ids = [r["id"] for r in entry.options[CONF_ROLES] if r["id"].startswith("custom_")]
    assert sorted(ids, key=lambda i: int(i.split("_")[1])) == [f"custom_{n}" for n in range(1, 11)]
    assert hass.states.get("binary_sensor.home_mode_custom_2") is not None
    assert "Cinema" in hass.states.get("select.home_mode").attributes["options"]


async def test_options_custom_menu_limits(hass: HomeAssistant, entry) -> None:
    """The add entry is hidden at ten custom modes and remove only shows with customs."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    assert "remove_custom" not in result["menu_options"]
    for n in range(1, 11):
        await _menu(hass, flow_id, "add_custom")
        result = await hass.config_entries.options.async_configure(flow_id, {"name": f"Mode {n}"})
    assert "add_custom" not in result["menu_options"]
    assert "remove_custom" in result["menu_options"]


async def test_options_remove_last_primary_blocked(hass: HomeAssistant) -> None:
    """Removing the only enabled primary (a custom mode) is rejected."""
    from .conftest import make_entry

    entry = make_entry()
    roles = [{**r, "enabled": r["id"] in {"guest", "dnd"}} for r in entry.options[CONF_ROLES]] + [
        {"id": "custom_1", "name": "Only", "enabled": True}
    ]
    entry = make_entry(options={CONF_ROLES: roles})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "remove_custom")
    result = await hass.config_entries.options.async_configure(flow_id, {"role": "custom_1"})
    assert result["errors"] == {"base": "no_primary"}


async def test_options_save_on_submit_without_done(hass: HomeAssistant, entry) -> None:
    """Every submitted screen is saved at once; closing the dialog keeps it."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "edit_role")
    await hass.config_entries.options.async_configure(flow_id, {"role": "night"})
    await hass.config_entries.options.async_configure(flow_id, {"name": "Sleep", "enabled": True})
    await _menu(hass, flow_id, "presence")
    await hass.config_entries.options.async_configure(
        flow_id, {"persons": [], "away_delay_min": 9, "vacation_after_h": 30}
    )
    # Close the dialog instead of picking Done.
    hass.config_entries.options.async_abort(flow_id)
    await hass.async_block_till_done()
    roles = {r["id"]: r for r in entry.options[CONF_ROLES]}
    assert roles["night"]["name"] == "Sleep"
    assert entry.options["away_delay_min"] == 9
    assert "Sleep" in hass.states.get("select.home_mode").attributes["options"]


async def test_options_pickers_can_go_back(hass: HomeAssistant, entry) -> None:
    """Every picker offers Back, preselected, and Back changes nothing."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "add_custom")
    await hass.config_entries.options.async_configure(flow_id, {"name": "Cinema"})
    before = dict(entry.options)
    for step, field in (
        ("edit_role", "role"),
        ("move_role", "role"),
        ("remove_custom", "role"),
        ("user_rules", "user"),
    ):
        result = await _menu(hass, flow_id, step)
        key = next(k for k in result["data_schema"].schema if str(k) == field)
        assert key.default() == "back"
        assert result["data_schema"].schema[key].config["options"][0]["value"] == "back"
        payload = {field: "back"}
        if step == "move_role":
            payload["direction"] = "up"
        result = await hass.config_entries.options.async_configure(flow_id, payload)
        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == ("init" if step == "user_rules" else "modes")
    # An empty name leaves "add a custom mode" without adding one.
    await _menu(hass, flow_id, "add_custom")
    result = await hass.config_entries.options.async_configure(flow_id, {})
    assert result["step_id"] == "modes"
    # An empty input_select leaves the import.
    await _menu(hass, flow_id, "integrations")
    await _menu(hass, flow_id, "import_input_select")
    result = await hass.config_entries.options.async_configure(flow_id, {})
    assert result["step_id"] == "integrations"
    assert dict(entry.options) == before


async def test_options_role_lists_only_offer_usable_modes(hass: HomeAssistant, entry) -> None:
    """Disabled modes are not offered where they cannot do anything."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "edit_role")
    await hass.config_entries.options.async_configure(flow_id, {"role": "dnd"})
    await hass.config_entries.options.async_configure(
        flow_id, {"name": "Do not disturb", "enabled": False}
    )
    await _menu(hass, flow_id, "integrations")
    result = await _menu(hass, flow_id, "actions")
    key = next(k for k in result["data_schema"].schema if str(k) == "role")
    offered = {o["value"] for o in result["data_schema"].schema[key].config["options"]}
    assert "dnd" not in offered and "guest" in offered
    await hass.config_entries.options.async_configure(
        flow_id, {"role": "back", "actions_timeout_s": 30}
    )
    result = await _menu(hass, flow_id, "vacation")
    key = next(k for k in result["data_schema"].schema if str(k) == "roles")
    offered = {o["value"] for o in result["data_schema"].schema[key].config["options"]}
    assert "guest" not in offered and "dnd" not in offered and "vacation" in offered


async def test_options_manual_only_is_exclusive(hass: HomeAssistant, entry) -> None:
    """'Manual only' together with another method is rejected."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    await _menu(hass, flow_id, "night")
    result = await hass.config_entries.options.async_configure(
        flow_id, {"methods": ["manual", "time_window"], "start": "22:00:00", "end": "06:00:00"}
    )
    assert result["errors"] == {"methods": "manual_exclusive"}
    result = await hass.config_entries.options.async_configure(
        flow_id, {"methods": ["manual"], "start": "22:00:00", "end": "06:00:00"}
    )
    assert result["type"] is FlowResultType.MENU
    await _menu(hass, flow_id, "morning")
    result = await hass.config_entries.options.async_configure(
        flow_id,
        {"methods": ["manual", "time"], "time": "07:00:00", "earliest": "05:00:00"},
    )
    assert result["errors"] == {"methods": "manual_exclusive"}


async def test_first_setup_presence_and_night_by_the_clock(hass: HomeAssistant) -> None:
    """The optional setup screens store presence and a clock-based night and morning."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = result["flow_id"]
    await hass.config_entries.flow.async_configure(flow_id, {CONF_PRESET: "simple"})
    hass.states.async_set("person.anna", "home")
    await hass.config_entries.flow.async_configure(
        flow_id, {"persons": ["person.anna"], "away_delay_min": 7}
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"night_by_time": True, "night_start": "23:00:00", "morning_time": "23:00:00"}
    )
    assert result["errors"] == {"morning_time": "same_time"}
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"night_by_time": True, "night_start": "23:00:00", "morning_time": "06:30:00"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = hass.config_entries.async_entries(DOMAIN)[0].options
    assert options["persons"] == ["person.anna"]
    assert options["away_delay_min"] == 7
    assert options["night"] == {
        "methods": ["time_window"],
        "start": "23:00:00",
        "end": "06:30:00",
    }
    assert options["morning"] == {"methods": ["time"], "time": "06:30:00"}

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    summary = result["description_placeholders"]["summary"]
    assert "**Presence:** 1 person, Away after 7 min" in summary
    assert "**Night:** at 23:00" in summary
    assert "**Morning:** at 06:30" in summary
    result = await options_menu(hass, result["flow_id"], "automation")
    assert result["menu_options"] == ["presence", "night", "morning", "override", "init"]
