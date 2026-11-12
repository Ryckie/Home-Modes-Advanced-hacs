"""Example blueprints: valid YAML, role based (never names), and working after a rename."""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.blueprint import models as bp_models
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import loader as ha_yaml
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import call, setup_entry

BLUEPRINTS = Path(__file__).parents[1] / "blueprints" / "automation" / "home_modes"
FILES = sorted(BLUEPRINTS.glob("*.yaml"))
ROLE_SENSOR = re.compile(r"^binary_sensor\.home_mode_[a-z0-9_]+$")


def test_there_are_three_blueprints() -> None:
    """The three examples of the brief exist."""
    assert [f.name for f in FILES] == [
        "heating_setback_away_vacation.yaml",
        "lights_off_at_night.yaml",
        "notify_vacation_or_guest.yaml",
    ]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_blueprint_is_valid(path: Path) -> None:
    """Home Assistant's own loader and blueprint schema accept the file."""
    data = ha_yaml.load_yaml(str(path))
    blueprint = bp_models.Blueprint(
        data, expected_domain="automation", path=path.name, schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.metadata["domain"] == "automation"
    assert blueprint.metadata["source_url"].endswith(f"/{path.name}")
    assert blueprint.metadata["homeassistant"]["min_version"] == "2026.10.4"
    # every input has a name; every role input is limited to this integration's sensors
    for name, spec in blueprint.inputs.items():
        assert spec is not None and "name" in spec, name


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_blueprints_use_roles_not_names(path: Path) -> None:
    """No mode name and no select state is used; role sensors are the only mode inputs."""
    text = path.read_text(encoding="utf-8")
    raw = yaml.load(text, Loader=_loader())
    assert "select.home_mode" not in text  # the select's state is the (renameable) name
    assert not re.search(r"\bto:\s*[\"']?(Home|Night|Away|Vacation|Guest)\b", text)
    assert not re.search(r"state:\s*[\"']?(Home|Night|Away|Vacation|Guest)[\"']?\s*$", text, re.M)
    role_inputs = [
        (key, spec) for key, spec in raw["blueprint"]["input"].items() if key.endswith("_sensor")
    ]
    assert role_inputs
    for key, spec in role_inputs:
        selector = spec["selector"]["entity"]
        assert selector["domain"] == "binary_sensor", key
        assert selector["integration"] == "home_modes", key
        assert ROLE_SENSOR.match(spec["default"]), key
    # The logic really is conditioned on those sensors.
    assert "condition: state" in text or "is_state(" in text


def _loader() -> type[yaml.SafeLoader]:
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!input", lambda loader, node: f"!input {node.value}")
    return Loader


# --- running them ---------------------------------------------------------------------------


@pytest.fixture
def blueprint_config(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Install the blueprints in a throw-away config directory."""
    target = tmp_path / "blueprints" / "automation" / "home_modes"
    target.mkdir(parents=True)
    for path in FILES:
        shutil.copy(path, target / path.name)
    hass.config.config_dir = str(tmp_path)
    return tmp_path


def _use(name: str, **inputs: Any) -> dict[str, Any]:
    return {
        "alias": name,
        "use_blueprint": {"path": f"home_modes/{name}.yaml", "input": inputs},
    }


async def _rename(hass: HomeAssistant, entry, role_id: str, new_name: str) -> None:
    roles = [dict(r) for r in entry.options["roles"]]
    next(r for r in roles if r["id"] == role_id)["name"] = new_name
    hass.config_entries.async_update_entry(entry, options={**entry.options, "roles": roles})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def _settle_delay(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the blueprint's settle delay (5 s) pass.

    async_block_till_done would wait for the delayed run forever under frozen time, so
    yield to the loop a few times, then move the clock and fire the timer.
    """
    for _ in range(10):
        await asyncio.sleep(0)
    freezer.tick(timedelta(seconds=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _fake_lights(hass: HomeAssistant) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def handle(call: ServiceCall) -> None:
        seen.append({"service": call.service, **dict(call.data)})

    hass.services.async_register("light", "turn_off", handle)
    return seen


async def test_lights_off_at_night_survives_a_rename(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, blueprint_config: Path
) -> None:
    """Night makes the lights go off; after renaming Night to Sleep it still does."""
    seen = _fake_lights(hass)
    entry = await setup_entry(hass, freezer)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                _use(
                    "lights_off_at_night",
                    lights={"entity_id": ["light.living"]},
                    transition=2,
                    skip_while_on="binary_sensor.home_mode_guest",
                )
            ]
        },
    )
    await hass.async_block_till_done()
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert [s["entity_id"] for s in seen] == [["light.living"]]
    assert seen[0]["transition"] == 2

    # Reloading the integration while Night is active does not run it again.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(seen) == 1
    await call(hass, "set_mode", {"mode": "home"})
    await _rename(hass, entry, "night", "Sleep")
    assert hass.states.get("select.home_mode").attributes["options"].count("Sleep") == 1
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert len(seen) == 2  # fired again under the new name

    # The optional guard: with the Guest overlay on, the lights are left alone.
    await call(hass, "set_mode", {"mode": "home"})
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert len(seen) == 2


async def test_heating_setback_in_away_and_vacation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, blueprint_config: Path
) -> None:
    """Away or Vacation lowers the target; leaving both restores it; works after a rename."""
    calls = async_mock_service(hass, "climate", "set_temperature")
    entry = await setup_entry(hass, freezer)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                _use(
                    "heating_setback_away_vacation",
                    thermostats={"entity_id": ["climate.hall"]},
                    setback_temperature=15.5,
                    normal_temperature=21,
                    settle_seconds=5,
                )
            ]
        },
    )
    await hass.async_block_till_done()

    async def temperatures() -> list[float]:
        await _settle_delay(hass, freezer)
        return [c.data["temperature"] for c in calls]

    await call(hass, "set_mode", {"mode": "away"})
    assert [float(t) for t in await temperatures()] == [15.5]
    calls.clear()
    await call(hass, "set_mode", {"mode": "vacation"})  # away -> vacation: still setback
    result = await temperatures()
    assert [float(t) for t in result] == [15.5]  # Away off, Vacation on: no bump to 21
    calls.clear()
    await call(hass, "set_mode", {"mode": "home"})
    assert [float(t) for t in await temperatures()] == [21.0]

    # After renaming both roles the same thing happens.
    await _rename(hass, entry, "away", "Out")
    await _rename(hass, entry, "vacation", "Holiday")
    calls.clear()
    await call(hass, "set_mode", {"mode": "away"})
    assert [float(t) for t in await temperatures()] == [15.5]
    calls.clear()
    await call(hass, "set_mode", {"mode": "home"})
    assert [float(t) for t in await temperatures()] == [21.0]
    assert all(c.data["entity_id"] == ["climate.hall"] for c in calls)


async def test_notify_on_vacation_or_guest(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, blueprint_config: Path
) -> None:
    """The user's action runs with {{ message }} and {{ what }}; renaming changes nothing."""
    sent: list[dict[str, Any]] = []

    async def notify(call: ServiceCall) -> None:
        sent.append(dict(call.data))

    hass.services.async_register("notify", "mobile_app_pixel", notify)
    entry = await setup_entry(hass, freezer)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                _use(
                    "notify_vacation_or_guest",
                    notify_actions=[
                        {
                            "action": "notify.mobile_app_pixel",
                            "data": {"message": "{{ message }}", "title": "{{ what }}"},
                        }
                    ],
                    guest_message="Guests are here",
                )
            ]
        },
    )
    await hass.async_block_till_done()
    await call(hass, "set_mode", {"mode": "vacation"})
    await hass.async_block_till_done()
    assert sent == [{"message": "House mode: Vacation started.", "title": "vacation"}]
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert sent[-1] == {"message": "Guests are here", "title": "guest"}
    # Other modes do not notify.
    count = len(sent)
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert len(sent) == count

    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await call(hass, "set_mode", {"mode": "home"})
    await _rename(hass, entry, "vacation", "Holiday")
    await _rename(hass, entry, "guest", "Visitors")
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert sent[-1]["title"] == "guest"
    await call(hass, "set_overlay", {"overlay": "guest", "active": False})
    await call(hass, "set_mode", {"mode": "vacation"})
    await hass.async_block_till_done()
    assert sent[-1]["title"] == "vacation"
