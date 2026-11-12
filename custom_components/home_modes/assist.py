"""Assist (conversation) intents: set the house mode and turn overlays on or off.

The handlers register with the intent helper. Sentences are NOT shipped by the
integration (Home Assistant has no mechanism for that, see docs/assist.md); users add
custom sentences that trigger these intents.
"""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent

from .const import DOMAIN, INTENT_SET_MODE, INTENT_SET_OVERLAY
from .models import ChangeResult, ChangeSource, ChangeStatus, Role, RoleKind

SLOT_MODE = "mode"
SLOT_OVERLAY = "overlay"
SLOT_STATE = "state"
STATE_ON_WORDS = frozenset({"on", "active", "enable", "enabled", "start"})
STATE_OFF_WORDS = frozenset({"off", "inactive", "disable", "disabled", "stop"})


@callback
def async_register_intents(hass: HomeAssistant) -> None:
    """Register the intent handlers (called once from async_setup)."""
    intent.async_register(hass, SetModeIntent())
    intent.async_register(hass, SetOverlayIntent())


def _runtime(hass: HomeAssistant) -> Any:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def _error(
    intent_obj: intent.Intent, code: intent.IntentResponseErrorCode, text: str
) -> intent.IntentResponse:
    response = intent_obj.create_response()
    response.async_set_error(code, text)
    return response


def _speech(intent_obj: intent.Intent, text: str) -> intent.IntentResponse:
    response = intent_obj.create_response()
    response.async_set_speech(text)
    return response


def _failed(intent_obj: intent.Intent, result: ChangeResult, role: Role) -> intent.IntentResponse:
    """Turn a rejected or denied result into a spoken error."""
    code = intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    if result.status is ChangeStatus.DENIED:
        return _error(intent_obj, code, f"You are not allowed to change {role.name}.")
    if result.reason == "role_disabled":
        return _error(intent_obj, code, f"{role.name} is turned off in Home Modes.")
    if result.reason == "no_previous":
        return _error(intent_obj, code, "There is no previous mode.")
    return _error(intent_obj, code, f"I could not change {role.name}.")


class _HomeModesIntent(intent.IntentHandler):
    """Shared lookup of the runtime and of the role named by a slot."""

    def _find(
        self, intent_obj: intent.Intent, slot: str, kind: RoleKind
    ) -> tuple[Any, Role | intent.IntentResponse]:
        runtime = _runtime(intent_obj.hass)
        if runtime is None:
            return None, _error(
                intent_obj,
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Home Modes is not loaded.",
            )
        slots = self.async_validate_slots(intent_obj.slots)
        value = str(slots[slot]["value"])
        role = runtime.coordinator.find_role(value)
        is_overlay = role is not None and role.kind is RoleKind.OVERLAY
        if role is None:
            return runtime, _error(
                intent_obj,
                intent.IntentResponseErrorCode.NO_VALID_TARGETS,
                f"I don't know a mode called {value}.",
            )
        if is_overlay != (kind is RoleKind.OVERLAY):
            what = "an overlay" if is_overlay else "a house mode"
            return runtime, _error(
                intent_obj,
                intent.IntentResponseErrorCode.NO_VALID_TARGETS,
                f"{role.name} is {what}, not what you asked for.",
            )
        return runtime, role


class SetModeIntent(_HomeModesIntent):
    """Set the primary house mode."""

    intent_type = INTENT_SET_MODE
    description = "Sets the house mode (Home, Night, Away, ...)"
    slot_schema = {vol.Required(SLOT_MODE): intent.non_empty_string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Set the mode as the user of the conversation (no user: trusted, as services)."""
        runtime, role = self._find(intent_obj, SLOT_MODE, RoleKind.PRIMARY)
        if isinstance(role, intent.IntentResponse):
            return role
        result = await runtime.engine.async_set_primary(
            role.id, ChangeSource.MANUAL, context=intent_obj.context
        )
        if result.status is ChangeStatus.UNCHANGED:
            return _speech(intent_obj, f"The house is already in {role.name} mode.")
        if result.status is not ChangeStatus.APPLIED:
            return _failed(intent_obj, result, role)
        return _speech(intent_obj, f"House mode set to {role.name}.")


class SetOverlayIntent(_HomeModesIntent):
    """Turn an overlay (guest, do not disturb) on or off."""

    intent_type = INTENT_SET_OVERLAY
    description = "Turns an overlay such as Guest or Do not disturb on or off"
    slot_schema = {
        vol.Required(SLOT_OVERLAY): intent.non_empty_string,
        vol.Required(SLOT_STATE): intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Turn the overlay on or off as the user of the conversation."""
        runtime, role = self._find(intent_obj, SLOT_OVERLAY, RoleKind.OVERLAY)
        if isinstance(role, intent.IntentResponse):
            return role
        word = str(self.async_validate_slots(intent_obj.slots)[SLOT_STATE]["value"]).casefold()
        if word in STATE_ON_WORDS:
            active = True
        elif word in STATE_OFF_WORDS:
            active = False
        else:
            return _error(
                intent_obj,
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Say whether to turn it on or off.",
            )
        result = await runtime.engine.async_set_overlay(
            role.id, active, ChangeSource.MANUAL, context=intent_obj.context
        )
        label = "on" if active else "off"
        if result.status is ChangeStatus.UNCHANGED:
            return _speech(intent_obj, f"{role.name} is already {label}.")
        if result.status is not ChangeStatus.APPLIED:
            return _failed(intent_obj, result, role)
        return _speech(intent_obj, f"{role.name} is now {label}.")
