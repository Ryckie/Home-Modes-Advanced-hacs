"""Tests for the config and options flows."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.home_modes.const import CONF_PRESET, CONF_ROLES, DOMAIN


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
    return await hass.config_entries.options.async_configure(flow_id, {"next_step_id": step})


async def test_options_menu_and_rename_toggle(hass: HomeAssistant, entry) -> None:
    """Renaming and toggling a role saves and reloads the entry."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "edit_role",
        "move_role",
        "presence",
        "night",
        "morning",
        "override",
        "user_rules",
        "add_custom",
        "integrations",
        "save",
    ]
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

    step = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "remove_custom"}
    )
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
