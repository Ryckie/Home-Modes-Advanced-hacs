"""Failure modes: a removed person, a missing notify target, an action for a deleted role."""

from __future__ import annotations

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .helpers import advance, call, data, presence_options, primary, setup_entry

HOME2 = {"person.anna": "home", "person.ben": "home"}


async def test_removed_person_entity_does_not_change_the_mode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Deleting a tracked person (state removed) counts as 'not changed'."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    hass.states.async_remove("person.anna")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=48)
    assert primary(entry) == "home"
    assert data(entry).all_away_since is None
    # The remaining person leaving does not make everyone "away" while Anna is unknown.
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=48)
    assert primary(entry) == "home"


async def test_missing_notify_service_is_isolated(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog
) -> None:
    """A notify service that does not exist (removed app) never blocks the change."""
    entry = await setup_entry(
        hass,
        freezer,
        {"notify": {"rules": [{"event": "any_change", "services": ["mobile_app_gone"]}]}},
    )
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert primary(entry) == "night"
    ours = "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components.home_modes")
    )
    assert "mobile_app_gone" not in ours


async def test_action_that_targets_a_deleted_role_is_rejected(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A service call naming a role that no longer exists fails cleanly and changes nothing."""
    entry = await setup_entry(hass, freezer)
    with pytest.raises(HomeAssistantError):
        await call(hass, "set_mode", {"mode": "custom_9"})
    assert primary(entry) == "home"
