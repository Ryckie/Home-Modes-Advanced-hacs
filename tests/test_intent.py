"""Assist intents: set the house mode and overlays."""

from __future__ import annotations

import shutil
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component

from custom_components.home_modes.const import INTENT_SET_MODE, INTENT_SET_OVERLAY

from .helpers import primary, setup_entry

SENTENCES = Path(__file__).parents[1] / "docs" / "examples" / "home_modes_sentences.yaml"


async def _handle(hass: HomeAssistant, intent_type: str, slots: dict, user_id: str | None = None):
    return await intent.async_handle(
        hass,
        "test",
        intent_type,
        {k: {"value": v} for k, v in slots.items()},
        context=Context(user_id=user_id) if user_id else Context(),
    )


def _speech(response) -> str:
    return response.speech["plain"]["speech"]


async def test_intent_sets_the_mode(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The intent changes the mode by name or id and answers in words."""
    entry = await setup_entry(hass, freezer)
    response = await _handle(hass, INTENT_SET_MODE, {"mode": "night"})
    assert primary(entry) == "night"
    assert _speech(response) == "House mode set to Night."
    response = await _handle(hass, INTENT_SET_MODE, {"mode": "  HOME "})
    assert primary(entry) == "home"
    again = await _handle(hass, INTENT_SET_MODE, {"mode": "Home"})
    assert _speech(again) == "The house is already in Home mode."


async def test_intent_rejects_unknown_disabled_and_wrong_kind(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Unknown modes, disabled modes and overlays asked as a mode are refused clearly."""
    entry = await setup_entry(hass, freezer)
    roles = [
        {**r, "enabled": False} if r["id"] == "vacation" else r for r in entry.options["roles"]
    ]
    hass.config_entries.async_update_entry(entry, options={**entry.options, "roles": roles})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    unknown = await _handle(hass, INTENT_SET_MODE, {"mode": "Banana"})
    assert unknown.response_type is intent.IntentResponseType.ERROR
    assert unknown.error_code is intent.IntentResponseErrorCode.NO_VALID_TARGETS
    assert "Banana" in _speech(unknown)

    disabled = await _handle(hass, INTENT_SET_MODE, {"mode": "vacation"})
    assert disabled.response_type is intent.IntentResponseType.ERROR
    assert "turned off" in _speech(disabled)
    assert primary(entry) == "home"

    overlay_as_mode = await _handle(hass, INTENT_SET_MODE, {"mode": "guest"})
    assert overlay_as_mode.response_type is intent.IntentResponseType.ERROR
    assert "overlay" in _speech(overlay_as_mode)


async def test_intent_overlay_on_off(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Overlays turn on and off; invalid state words and unknown overlays are refused."""
    entry = await setup_entry(hass, freezer)
    on = await _handle(hass, INTENT_SET_OVERLAY, {"overlay": "guest", "state": "on"})
    assert _speech(on) == "Guest is now on."
    assert "guest" in entry.runtime_data.coordinator.data.overlays
    again = await _handle(hass, INTENT_SET_OVERLAY, {"overlay": "Guest", "state": "on"})
    assert _speech(again) == "Guest is already on."
    off = await _handle(hass, INTENT_SET_OVERLAY, {"overlay": "guest", "state": "off"})
    assert _speech(off) == "Guest is now off."
    assert entry.runtime_data.coordinator.data.overlays == ()
    bad = await _handle(hass, INTENT_SET_OVERLAY, {"overlay": "guest", "state": "sideways"})
    assert bad.response_type is intent.IntentResponseType.ERROR
    unknown = await _handle(hass, INTENT_SET_OVERLAY, {"overlay": "nothing", "state": "on"})
    assert unknown.error_code is intent.IntentResponseErrorCode.NO_VALID_TARGETS
    as_overlay = await _handle(hass, INTENT_SET_OVERLAY, {"overlay": "night", "state": "on"})
    assert as_overlay.response_type is intent.IntentResponseType.ERROR


async def test_intent_enforces_permissions(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user, hass_admin_user
) -> None:
    """The conversation user's allow-list applies; admins and no-user calls are trusted."""
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    denied = await _handle(hass, INTENT_SET_MODE, {"mode": "night"}, user_id=guest_user.id)
    assert denied.response_type is intent.IntentResponseType.ERROR
    assert "not allowed" in _speech(denied)
    assert primary(entry) == "home"
    denied_overlay = await _handle(
        hass, INTENT_SET_OVERLAY, {"overlay": "guest", "state": "on"}, user_id=guest_user.id
    )
    assert "not allowed" in _speech(denied_overlay)
    assert entry.runtime_data.coordinator.data.overlays == ()

    allowed = await _handle(hass, INTENT_SET_MODE, {"mode": "home"}, user_id=guest_user.id)
    assert allowed.response_type is intent.IntentResponseType.ACTION_DONE or "already" in _speech(
        allowed
    )

    admin = await _handle(hass, INTENT_SET_MODE, {"mode": "night"}, user_id=hass_admin_user.id)
    assert primary(entry) == "night"
    assert _speech(admin) == "House mode set to Night."
    # Voice satellites send no user: same trust as automations (documented in docs/assist.md).
    await _handle(hass, INTENT_SET_MODE, {"mode": "away"})
    assert primary(entry) == "away"


async def test_intent_denied_attempts_are_in_the_history(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """A denied voice command leaves the same history entry as a denied service call."""
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )
    await _handle(hass, INTENT_SET_MODE, {"mode": "night"}, user_id=guest_user.id)
    await hass.async_block_till_done()
    assert [e["kind"] for e in entry.runtime_data.history.entries][-1] == "denied"


async def test_intent_without_loaded_entry(hass: HomeAssistant) -> None:
    """A clear answer is given when Home Modes is not loaded."""
    assert await async_setup_component(hass, "home_modes", {})
    response = await _handle(hass, INTENT_SET_MODE, {"mode": "night"})
    assert response.response_type is intent.IntentResponseType.ERROR
    assert "not loaded" in _speech(response)


async def test_documented_sentences_work_end_to_end(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """The example in docs/assist.md, copied to custom_sentences, drives the intents."""
    target = Path(hass.config.config_dir) / "custom_sentences" / "en"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(SENTENCES, target / "home_modes.yaml")
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    entry = await setup_entry(
        hass,
        freezer,
        {"user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}}},
    )

    async def say(text: str, user_id: str | None = None):
        return await conversation.async_converse(
            hass,
            text,
            None,
            Context(user_id=user_id) if user_id else Context(),
            language="en",
            agent_id=conversation.HOME_ASSISTANT_AGENT,
        )

    result = await say("set the house mode to night")
    assert primary(entry) == "night"
    assert result.response.speech["plain"]["speech"] == "House mode set to Night."

    await say("turn on the guest mode")
    assert entry.runtime_data.coordinator.data.overlays == ("guest",)
    await say("turn do not disturb mode on")
    assert entry.runtime_data.coordinator.data.overlays == ("guest", "dnd")
    await say("turn off guest mode")
    assert entry.runtime_data.coordinator.data.overlays == ("dnd",)

    unknown = await say("set the house mode to banana")
    assert unknown.response.response_type is intent.IntentResponseType.ERROR

    denied = await say("set the house mode to away", user_id=guest_user.id)
    assert primary(entry) == "night"
    assert "not allowed" in denied.response.speech["plain"]["speech"]
