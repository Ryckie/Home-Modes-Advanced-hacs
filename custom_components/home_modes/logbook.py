"""Describe Home Modes events in the logbook."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
    LazyEventPartialState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, EVENT_CHANGED, EVENT_DENIED, KEY_SELECT, TITLE


def _role_name(hass: HomeAssistant, role_id: str | None) -> str | None:
    if role_id is None:
        return None
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        role = entry.runtime_data.coordinator.role(role_id)
        if role is not None:
            return role.name
    return role_id


def _select_entity(hass: HomeAssistant) -> str | None:
    registry = er.async_get(hass)
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return registry.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_{KEY_SELECT}")
    return None


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, Any]]], None
    ],
) -> None:
    """Describe home_modes_changed and home_modes_denied."""

    @callback
    def describe_changed(event: LazyEventPartialState) -> dict[str, Any]:
        data = event.data
        name = _role_name(hass, data.get("role")) or "?"
        if data.get("kind") == "overlay":
            what = f"{name} turned {'on' if data.get('active') else 'off'}"
        else:
            previous = _role_name(hass, data.get("from"))
            what = f"changed from {previous} to {name}" if previous else f"changed to {name}"
        details = [f"source: {data.get('source')}"]
        if data.get("rule"):
            details.append(f"rule: {data['rule']}")
        return {
            LOGBOOK_ENTRY_NAME: TITLE,
            LOGBOOK_ENTRY_MESSAGE: f"{what} ({', '.join(details)})",
            LOGBOOK_ENTRY_ENTITY_ID: _select_entity(hass),
        }

    @callback
    def describe_denied(event: LazyEventPartialState) -> dict[str, Any]:
        data = event.data
        name = _role_name(hass, data.get("role")) or "the auto switch"
        return {
            LOGBOOK_ENTRY_NAME: TITLE,
            LOGBOOK_ENTRY_MESSAGE: f"denied change of {name} (reason: {data.get('reason')})",
            LOGBOOK_ENTRY_ENTITY_ID: _select_entity(hass),
        }

    async_describe_event(DOMAIN, EVENT_CHANGED, describe_changed)
    async_describe_event(DOMAIN, EVENT_DENIED, describe_denied)
