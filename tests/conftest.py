"""Fixtures for Home Modes Advanced tests."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_modes.config_flow import build_preset_roles
from custom_components.home_modes.const import CONF_PRESET, CONF_ROLES, DOMAIN, PRESET_EXTENDED


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading of the custom integration in every test."""


def disable_derived(entry_options: dict[str, Any]) -> dict[str, Any]:
    """Return options with all_home and all_away disabled."""
    roles = [
        {**r, "enabled": False} if r["id"] in ("all_home", "all_away") else r
        for r in entry_options[CONF_ROLES]
    ]
    return {**entry_options, CONF_ROLES: roles}


def make_entry(
    preset: str = PRESET_EXTENDED,
    options: dict[str, Any] | None = None,
    *,
    derived: bool = True,
) -> MockConfigEntry:
    """Create a config entry for a preset (derived=False disables all_home/all_away)."""
    base: dict[str, Any] = {CONF_ROLES: build_preset_roles(preset)}
    if not derived:
        base = disable_derived(base)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home Modes",
        data={CONF_PRESET: preset},
        options={**base, **(options or {})},
    )


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the integration with the extended preset, all_home/all_away disabled."""
    config_entry = make_entry(derived=False)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
async def guest_user(hass: HomeAssistant, hass_admin_user):
    """Return a non-admin user (the first user created would become the owner)."""
    return await hass.auth.async_create_user("Guest", group_ids=[GROUP_ID_USER])
