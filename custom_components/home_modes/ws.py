"""Websocket API: read-only access to the history for the dashboard card."""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, ROLE_ICONS, WS_ALLOWED_ROLES, WS_HISTORY
from .models import Role
from .permissions import auto_control_allowed, role_allowed

MAX_LIMIT = 500


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_history)
    websocket_api.async_register_command(hass, ws_allowed_roles)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_HISTORY,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=MAX_LIMIT)),
    }
)
@websocket_api.async_response
async def ws_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the newest history entries the current user may see (read-only)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Home Modes is not loaded")
        return
    user = connection.user
    history = entries[0].runtime_data.history
    connection.send_result(
        msg["id"],
        {"entries": history.visible_entries(msg["limit"], is_admin=user.is_admin, user_id=user.id)},
    )


def _public_role(role: Role) -> dict[str, Any]:
    """Return the fields of a role the cards need (never actions or other settings)."""
    return {
        "id": role.id,
        "name": role.name,
        "type": role.type.value,
        "icon": ROLE_ICONS.get(role.type.value),
    }


@websocket_api.websocket_command({vol.Required("type"): WS_ALLOWED_ROLES})
@callback
def ws_allowed_roles(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the roles the calling user may set (any logged-in user).

    Only the caller's own permissions are used and returned; other users' rules are
    never sent. This only decides what a card shows. The services and the select
    entity enforce the same rule on the server.
    """
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Home Modes is not loaded")
        return
    coordinator = entries[0].runtime_data.coordinator
    user = connection.user
    rule = coordinator.user_rules.get(user.id)
    is_admin = user.is_admin
    connection.send_result(
        msg["id"],
        {
            "modes": [
                _public_role(r)
                for r in coordinator.selectable_primaries
                if role_allowed(is_admin, rule, r.id)
            ],
            "overlays": [
                _public_role(r)
                for r in coordinator.overlay_roles
                if role_allowed(is_admin, rule, r.id)
            ],
            "can_set_auto": auto_control_allowed(is_admin, rule),
        },
    )
