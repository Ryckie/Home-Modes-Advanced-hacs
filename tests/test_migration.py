"""Migration helper: suggestions, preview, service, options flow, usage report."""

from __future__ import annotations

import json

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_modes.config_flow import build_preset_roles
from custom_components.home_modes.migration import (
    TARGET_CUSTOM,
    TARGET_SKIP,
    build_plan,
    suggest_mapping,
)
from custom_components.home_modes.models import Role

from .helpers import options_menu, setup_entry

TYPICAL = ["Home", "Night", "Away", "Vacation"]
EXTRA = [
    "At home",
    "Sleeping",
    "Out",
    "Holiday",
    "Guests",
    "Do not disturb",
    "Movie night",
    "Party",
]


def _roles() -> list[Role]:
    return [Role.from_dict(r) for r in build_preset_roles("extended")]


def test_suggestions_by_name() -> None:
    """Names are matched to roles; anything else becomes a custom mode."""
    assert suggest_mapping(TYPICAL, _roles()) == {
        "Home": "home",
        "Night": "night",
        "Away": "away",
        "Vacation": "vacation",
    }
    result = suggest_mapping(["Sleeping", "Out", "Holiday", "Guests", "Quiet", "Bedtime"], _roles())
    assert result == {
        "Sleeping": "night",
        "Out": "away",
        "Holiday": "vacation",
        "Guests": "guest",
        "Quiet": "dnd",
        "Bedtime": TARGET_CUSTOM,  # night is already taken by "Sleeping"
    }
    assert suggest_mapping(["Movie", "Party"], _roles()) == {
        "Movie": TARGET_CUSTOM,
        "Party": TARGET_CUSTOM,
    }


def test_documented_worked_example() -> None:
    """The household example in docs/migration.md gives exactly the documented table."""
    assert suggest_mapping(
        ["At home", "Sleeping", "Out", "Holiday", "Guests", "Movie night", "Party"], _roles()
    ) == {
        "At home": "home",
        "Sleeping": "night",
        "Out": "away",
        "Holiday": "vacation",
        "Guests": "guest",
        "Movie night": TARGET_CUSTOM,
        "Party": TARGET_CUSTOM,
    }


def test_suggestion_prefers_an_existing_exact_name_and_respects_the_cap() -> None:
    """An existing role with the same name wins; custom modes stop at the cap."""
    roles = [*_roles(), Role("custom_1", "Movie")]
    assert suggest_mapping(["movie"], roles) == {"movie": "custom_1"}
    options = [f"Scene {n}" for n in range(1, 13)]
    mapping = suggest_mapping(options, _roles())
    assert list(mapping.values()).count(TARGET_CUSTOM) == 10
    assert list(mapping.values()).count(TARGET_SKIP) == 2


def test_plan_validation() -> None:
    """Duplicates, unknown targets and missing rows are errors; nothing is half applied."""
    roles = _roles()
    assert "duplicate_role:home" in build_plan(roles, ["a", "b"], {"a": "home", "b": "home"}).errors
    assert build_plan(roles, ["a"], {"a": "nope"}).errors == ["unknown_target:a"]
    assert build_plan(roles, ["a"], {"a": "all_home"}).errors == ["unknown_target:a"]
    assert build_plan(roles, ["a", "b"], {"a": "home"}).errors == ["missing_mapping:b"]
    clash = build_plan(roles, ["Night"], {"Night": "home"})  # would give two roles the name Night
    assert clash.errors == ["name_exists"]
    ok = build_plan(roles, ["Living", "Movie"], {"Living": "home", "Movie": TARGET_CUSTOM})
    assert ok.valid
    assert [r.name for r in ok.roles if r.id in ("home", "custom_1")] == ["Living", "Movie"]
    assert ok.mirror_mapping == {"home": "Living", "custom_1": "Movie"}


async def _input_select(hass: HomeAssistant, options: list[str], initial: str | None = None) -> str:
    assert await async_setup_component(
        hass,
        "input_select",
        {"input_select": {"house": {"options": options, "initial": initial or options[0]}}},
    )
    await hass.async_block_till_done()
    return "input_select.house"


async def _import(hass: HomeAssistant, payload: dict, user_id: str | None = None):
    return await hass.services.async_call(
        "home_modes",
        "import_input_select",
        payload,
        blocking=True,
        return_response=True,
        context=Context(user_id=user_id) if user_id else Context(),
    )


async def test_service_preview_writes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without confirm the service only returns suggestions, preview and the usage report."""
    entry = await setup_entry(hass, freezer)
    before = json.dumps(dict(entry.options), sort_keys=True)
    entity = await _input_select(hass, ["Living", "Sleeping", "Movie"])
    result = await _import(hass, {"entity_id": entity})
    assert result["applied"] is False
    assert result["suggestions"] == {"Living": "custom", "Sleeping": "night", "Movie": "custom"}
    assert [r["action"] for r in result["preview"]] == ["create", "rename", "create"]
    assert result["snippets"][1]["entity_id"] == "binary_sensor.home_mode_night"
    assert "entity_id: binary_sensor.home_mode_night" in result["snippets"][1]["condition"]
    assert json.dumps(dict(entry.options), sort_keys=True) == before


async def test_service_confirm_applies_with_the_users_names(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Confirm renames/enables roles, adds custom modes and stores the mirror setting (off)."""
    entry = await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["Living", "Sleeping", "Movie", "Skip me"])
    result = await _import(
        hass,
        {
            "entity_id": entity,
            "mapping": {"Living": "home", "Skip me": "skip"},
            "confirm": True,
        },
    )
    assert result["applied"] is True
    await hass.async_block_till_done()
    names = {r["id"]: r["name"] for r in entry.options["roles"]}
    assert names["home"] == "Living"
    assert names["night"] == "Sleeping"
    assert names["custom_1"] == "Movie"
    assert "Skip me" not in names.values()
    assert entry.options["mirror"] == {
        "enabled": False,
        "entity_id": entity,
        "mapping": {"home": "Living", "night": "Sleeping", "custom_1": "Movie"},
        "overlays": False,
    }
    # The reload picked the new names up, the old input_select is untouched.
    assert hass.states.get("select.home_mode").attributes["options"][:2] == ["Living", "Sleeping"]
    assert hass.states.get(entity).attributes["options"] == [
        "Living",
        "Sleeping",
        "Movie",
        "Skip me",
    ]


async def test_service_rejects_invalid_mappings_and_writes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Confirm with a bad mapping raises and leaves the options as they were."""
    entry = await setup_entry(hass, freezer)
    before = json.dumps(dict(entry.options), sort_keys=True)
    entity = await _input_select(hass, ["A", "B"])
    for mapping in ({"A": "home", "B": "home"}, {"A": "nope"}, {"Ghost": "home"}):
        with pytest.raises(ServiceValidationError):
            await _import(hass, {"entity_id": entity, "mapping": mapping, "confirm": True})
    with pytest.raises(ServiceValidationError):
        await _import(hass, {"entity_id": "input_select.missing", "confirm": True})
    assert json.dumps(dict(entry.options), sort_keys=True) == before


async def test_service_is_admin_only(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """A non-admin user cannot run the import."""
    await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["A"])
    with pytest.raises(Unauthorized):
        await _import(hass, {"entity_id": entity}, user_id=guest_user.id)


async def test_usage_report_is_read_only(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Automations, scripts and UI template helpers that use the input_select are listed."""
    entry = await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["Home", "Night"])
    automation_config = [
        {
            "id": "a1",
            "alias": "Lights when night",
            "trigger": {"platform": "state", "entity_id": entity, "to": "Night"},
            "action": [],
        },
        {
            "id": "a2",
            "alias": "Template user",
            "trigger": {"platform": "event", "event_type": "test_a2"},
            "condition": {
                "condition": "template",
                "value_template": "{{ is_state('input_select.house', 'Night') }}",
            },
            "action": [],
        },
        {
            "id": "a3",
            "alias": "Unrelated",
            "trigger": {"platform": "event", "event_type": "test_a3"},
            "action": [],
        },
    ]
    assert await async_setup_component(hass, "automation", {"automation": automation_config})
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "bedtime": {
                    "sequence": [
                        {
                            "action": "input_select.select_option",
                            "target": {"entity_id": entity},
                            "data": {"option": "Night"},
                        }
                    ]
                }
            }
        },
    )
    MockConfigEntry(
        domain="template",
        title="Night helper",
        options={"state": "{{ states('input_select.house') }}"},
    ).add_to_hass(hass)
    await hass.async_block_till_done()
    before = json.dumps(dict(entry.options), sort_keys=True)

    result = await _import(hass, {"entity_id": entity})
    usage = result["usage"]
    assert sorted(a["name"] for a in usage["automations"]) == ["Lights when night", "Template user"]
    by_name = {a["name"]: a for a in usage["automations"]}
    assert by_name["Lights when night"]["mentions"] == ["Night"]
    assert [s["entity_id"] for s in usage["scripts"]] == ["script.bedtime"]
    assert [t["name"] for t in usage["templates"]] == ["Night helper"]
    # Nothing was edited: same automations, same options.
    assert len(hass.states.async_entity_ids("automation")) == 3
    assert json.dumps(dict(entry.options), sort_keys=True) == before


async def _walk_to_confirm(hass: HomeAssistant, entry, entity: str, mapping: dict, mirror: bool):
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    configure = hass.config_entries.options.async_configure
    await options_menu(hass, flow_id, "integrations")
    result = await options_menu(hass, flow_id, "import_input_select")
    assert result["step_id"] == "import_input_select"
    result = await configure(flow_id, {"entity_id": entity})
    assert result["step_id"] == "import_map"
    result = await configure(flow_id, {**mapping, "mirror_to_old_input_select": mirror})
    return flow_id, result


async def test_options_flow_import_confirmed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The flow suggests, shows a preview and only writes after confirmation."""
    entry = await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["Home", "Night", "Movie"])
    before = json.dumps(dict(entry.options), sort_keys=True)
    flow_id, result = await _walk_to_confirm(
        hass, entry, entity, {"Home": "home", "Night": "night", "Movie": "custom"}, True
    )
    assert result["step_id"] == "import_confirm"
    assert "Movie" in result["description_placeholders"]["preview"]
    assert result["description_placeholders"]["mirror"] == "on"
    assert json.dumps(dict(entry.options), sort_keys=True) == before  # nothing written yet
    result = await hass.config_entries.options.async_configure(flow_id, {"confirm": True})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "integrations"
    await hass.async_block_till_done()
    assert entry.options["mirror"]["enabled"] is True
    assert {r["id"]: r["name"] for r in entry.options["roles"]}["custom_1"] == "Movie"


async def test_options_flow_import_declined_and_invalid(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Declining writes nothing; an invalid mapping stays on the mapping step."""
    entry = await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["A", "B"])
    before = json.dumps(dict(entry.options), sort_keys=True)
    flow_id, result = await _walk_to_confirm(hass, entry, entity, {"A": "home", "B": "home"}, False)
    assert result["step_id"] == "import_map"
    assert result["errors"] == {"base": "import_invalid"}
    result = await hass.config_entries.options.async_configure(
        flow_id, {"A": "home", "B": "night", "mirror_to_old_input_select": False}
    )
    assert result["step_id"] == "import_confirm"
    result = await hass.config_entries.options.async_configure(flow_id, {"confirm": False})
    assert result["type"] is FlowResultType.MENU
    hass.config_entries.options.async_abort(flow_id)
    assert json.dumps(dict(entry.options), sort_keys=True) == before


async def test_options_flow_import_keeps_earlier_edits(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Edits made earlier in the same options session are saved and kept by the import."""
    entry = await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["Home", "Night", "Movie"])
    configure = hass.config_entries.options.async_configure
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    # Unrelated edit: change the away delay on the presence screen (saved on submit).
    result = await options_menu(hass, flow_id, "presence")
    assert result["step_id"] == "presence"
    schema_keys = {str(k): k for k in result["data_schema"].schema}
    assert "away_delay_min" in schema_keys
    result = await configure(flow_id, {"persons": [], "away_delay_min": 17, "vacation_after_h": 48})
    assert result["type"] is FlowResultType.MENU
    # Role rename (also saved on submit).
    result = await options_menu(hass, flow_id, "edit_role")
    result = await configure(flow_id, {"role": "night"})
    result = await configure(flow_id, {"name": "Bedtime", "enabled": True})
    assert result["type"] is FlowResultType.MENU
    # Now the import.
    await options_menu(hass, flow_id, "integrations")
    await options_menu(hass, flow_id, "import_input_select")
    await configure(flow_id, {"entity_id": entity})
    result = await configure(
        flow_id,
        {
            "Home": "home",
            "Night": "night",
            "Movie": "custom",
            "mirror_to_old_input_select": True,
            "mirror_overlays": True,
        },
    )
    assert result["step_id"] == "import_confirm"
    assert result["description_placeholders"]["mirror_overlays"] == "on"
    result = await configure(flow_id, {"confirm": True})
    assert result["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    options = entry.options
    roles = {r["id"]: r for r in options["roles"]}
    assert roles["custom_1"]["name"] == "Movie"  # the import is there
    assert options["mirror"] == {
        "enabled": True,
        "entity_id": entity,
        "mapping": {"home": "Home", "night": "Night", "custom_1": "Movie"},
        "overlays": True,
    }
    # The earlier edits are kept; the import renamed Bedtime back to its option text.
    assert options["away_delay_min"] == 17
    assert options["vacation_after_h"] == 48
    assert roles["night"]["name"] == "Night"


async def test_options_flow_import_uses_saved_roles_in_the_preview(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The preview is built from the stored roles, which include earlier edits."""
    entry = await setup_entry(hass, freezer)
    entity = await _input_select(hass, ["Home", "Night"])
    configure = hass.config_entries.options.async_configure
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    await options_menu(hass, flow_id, "edit_role")
    await configure(flow_id, {"role": "night"})
    await configure(flow_id, {"name": "Bedtime", "enabled": True})
    await options_menu(hass, flow_id, "integrations")
    await options_menu(hass, flow_id, "import_input_select")
    await configure(flow_id, {"entity_id": entity})
    result = await configure(
        flow_id, {"Home": "home", "Night": "night", "mirror_to_old_input_select": False}
    )
    assert "was Bedtime" in result["description_placeholders"]["preview"]
    hass.config_entries.options.async_abort(flow_id)


async def test_service_keeps_mirror_overlays_unless_given(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The service keeps the stored "Mirror overlays" value when the field is left out."""
    entry = await setup_entry(
        hass,
        freezer,
        {"mirror": {"enabled": True, "entity_id": "input_select.x", "overlays": True}},
    )
    entity = await _input_select(hass, ["Home", "Night"])
    result = await _import(hass, {"entity_id": entity, "confirm": True, "mirror": True})
    assert result["mirror_overlays"] is True
    await hass.async_block_till_done()
    assert entry.options["mirror"]["overlays"] is True
    result = await _import(
        hass, {"entity_id": entity, "confirm": True, "mirror": True, "mirror_overlays": False}
    )
    assert result["mirror_overlays"] is False
