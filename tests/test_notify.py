"""Notifications: payloads, channels, templates, rate limit, isolation and defaults."""

from __future__ import annotations

import contextlib

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.home_modes.models import ChangeSource
from custom_components.home_modes.notify import (
    CHANNEL_ALERTS,
    CHANNEL_GUESTS,
    CHANNEL_MODE_CHANGES,
    build_payload,
)

from .helpers import advance, call, roles_without, setup_entry


def _rule(event: str, **extra) -> dict:
    return {"event": event, "services": ["mobile_app_pixel"], **extra}


def _opts(*rules: dict, **extra) -> dict:
    return {"notify": {"rules": list(rules), **extra}}


async def test_defaults_off(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """No rules, or rules without targets, send nothing."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    sent = async_mock_service(hass, "notify", "send_message")
    await setup_entry(hass, freezer)
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert not calls and not sent
    entry2_rules = _opts({"event": "any_change"})  # rule without any target
    from custom_components.home_modes.settings import parse_integration_settings

    assert parse_integration_settings(entry2_rules).notify.rules[0].targets == ()


async def test_rule_without_target_stays_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A rule without targets or services never sends."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, freezer, _opts({"event": "any_change"}))
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert not calls


async def test_payload_per_platform_and_channels(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, guest_user
) -> None:
    """Mode changes: HM_ModeChanges/low/passive; alerts: HM_Alerts/high/time-sensitive."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(
        hass,
        freezer,
        {
            **_opts(
                _rule("any_change"),
                _rule("denied"),
                _rule("guest_on"),
                _rule("vacation_entered"),
            ),
            "user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}},
        },
    )
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    data = calls[-1].data
    assert data["data"] == {
        "channel": CHANNEL_MODE_CHANGES,
        "importance": "low",
        "group": CHANNEL_MODE_CHANGES,
        "push": {"interruption-level": "passive"},
    }
    assert data["title"] == "Home Modes"

    with contextlib.suppress(HomeAssistantError):
        await call(hass, "set_mode", {"mode": "away"}, user_id=guest_user.id)
    await hass.async_block_till_done()
    alert = calls[-1].data
    assert alert["data"]["channel"] == CHANNEL_ALERTS == "HM_Alerts"
    assert alert["data"]["importance"] == "high"
    assert alert["data"]["push"]["interruption-level"] == "time-sensitive"
    assert "Guest" in alert["message"]

    before = len(calls)
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    guest = [c.data for c in calls[before:]]
    # guest_on wins over any_change (same text, duplicates are rate-limited)
    assert len(guest) == 1
    assert guest[0]["data"]["channel"] == CHANNEL_GUESTS == "HM_Guests"

    before = len(calls)
    await call(hass, "set_mode", {"mode": "vacation"})
    await hass.async_block_till_done()
    assert len(calls) - before == 1  # vacation_entered (any_change is the duplicate)
    assert calls[-1].data["data"]["channel"] == CHANNEL_MODE_CHANGES


def test_build_payload_fields() -> None:
    """The payload helper uses the documented Companion app field names."""
    payload = build_payload("guest_on", "hi", "T")
    assert payload == {
        "message": "hi",
        "title": "T",
        "data": {
            "channel": "HM_Guests",
            "importance": "default",
            "group": "HM_Guests",
            "push": {"interruption-level": "active"},
        },
    }


async def test_notify_entity_target(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Other notify entities are used through notify.send_message (message and title only)."""
    sent = async_mock_service(hass, "notify", "send_message")
    await setup_entry(
        hass, freezer, _opts({"event": "any_change", "targets": ["notify.phone"], "title": "Mode"})
    )
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert sent[0].data == {
        "entity_id": "notify.phone",
        "message": "Home mode: Home → Night",
        "title": "Mode",
    }


async def test_templates(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_admin_user
) -> None:
    """Templates get ids (from_role/to_role, aliases from_mode/to_mode) and names."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(
        hass,
        freezer,
        _opts(
            _rule(
                "changed_to",
                role="night",
                message="{{ from_role }}/{{ from_mode }}->{{ to_role }}/{{ to_mode }} "
                "{{ from_name }}->{{ to_name }} [{{ role }}] {{ source }}/{{ rule }} "
                "by {{ user }} at {{ time }}",
                title="{{ to_name | upper }}",
            ),
            _rule("changed_to", role="away", message="{{ unknown_function() }}"),
        ),
    )
    await call(hass, "set_mode", {"mode": "night"}, user_id=hass_admin_user.id)
    await hass.async_block_till_done()
    assert len(calls) == 1  # the away rule does not match
    expected = (
        f"home/home->night/night Home->Night [night] manual/ by {hass_admin_user.name} at 12:00"
    )
    assert calls[0].data["message"] == expected
    assert calls[0].data["title"] == "NIGHT"
    # a broken template falls back to the default text instead of failing
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert calls[-1].data["message"] == "Home mode: Night → Away"


async def test_rate_limit_duplicates(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The same message to the same target is sent at most once per 10 s."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, freezer, _opts(_rule("any_change")))
    await call(hass, "set_mode", {"mode": "away"})  # "Home -> Away"
    await call(hass, "set_mode", {"mode": "home"})
    await call(hass, "set_mode", {"mode": "away"})  # duplicate of the first, within 10 s
    await hass.async_block_till_done()
    assert [c.data["message"] for c in calls] == [
        "Home mode: Home → Away",
        "Home mode: Away → Home",
    ]
    await advance(hass, freezer, seconds=11)
    await call(hass, "set_mode", {"mode": "home"})
    await call(hass, "set_mode", {"mode": "away"})
    await hass.async_block_till_done()
    assert [c.data["message"] for c in calls][-2:] == [
        "Home mode: Away → Home",
        "Home mode: Home → Away",
    ]


async def test_rate_limit_configurable(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A rate limit of 0 sends every duplicate."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, freezer, _opts(_rule("any_change"), rate_limit_s=0))
    for mode in ("away", "home", "away"):
        await call(hass, "set_mode", {"mode": mode})
    await hass.async_block_till_done()
    assert len(calls) == 3


async def test_failing_notification_is_isolated(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog
) -> None:
    """A failing target is logged; the change and the other targets are unaffected."""

    async def broken(call: ServiceCall) -> None:
        raise HomeAssistantError("device offline")

    hass.services.async_register("notify", "mobile_app_broken", broken)
    ok = async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(
        hass,
        freezer,
        _opts({"event": "any_change", "services": ["mobile_app_broken", "mobile_app_pixel"]}),
    )
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.data.primary == "night"
    # Only this integration's records: with -v Home Assistant core logs every event at DEBUG,
    # including the registration of the test's own service.
    ours = "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components.home_modes")
    )
    assert "mobile_a… failed" in ours
    assert "mobile_app_broken" not in ours  # full targets are never logged
    assert len(ok) == 1


async def test_bridge_error_event(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Bridge errors notify through HM_Alerts."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, freezer, _opts(_rule("bridge_error")))
    entry.runtime_data.notifier.async_bridge_error("alarmo_unavailable: x")
    await hass.async_block_till_done()
    assert calls[0].data["data"]["channel"] == "HM_Alerts"
    assert "alarmo_unavailable" in calls[0].data["message"]


async def test_auto_change_notifies_with_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Template variables include the source of automatic changes."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, freezer, _opts(_rule("any_change", message="{{ source }}")))
    await entry.runtime_data.engine.async_set_primary("night", ChangeSource.SCHEDULE, rule="x")
    await hass.async_block_till_done()
    assert calls[0].data["message"] == "schedule"


async def test_variables_are_stable_when_renamed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """from_mode/to_mode always hold role ids, even for renamed modes; names are separate."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    roles = roles_without()
    for role in roles:
        if role["id"] == "night":
            role["name"] = "Sleeping"
    await setup_entry(
        hass,
        freezer,
        {
            "roles": roles,
            **_opts(_rule("any_change", message="{{ to_mode }}|{{ to_role }}|{{ to_name }}")),
        },
    )
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert calls[0].data["message"] == "night|night|Sleeping"


async def test_from_is_not_available(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """`from` is reserved in Jinja and not provided: it renders empty, so the default is used."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, freezer, _opts(_rule("any_change", message="{{ from }}")))
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert calls[0].data["message"] == "Home mode: Home → Night"  # fell back to the default


async def test_suppressed_messages_are_never_silent(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Rate-limited and most-specific-wins suppressions write a system history entry."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, freezer, _opts(_rule("guest_on"), _rule("any_change")))
    await call(hass, "set_overlay", {"overlay": "guest", "active": True})
    await hass.async_block_till_done()
    assert len(calls) == 1
    suppressed = [
        e for e in entry.runtime_data.history.entries if e["rule"] == "notification_suppressed"
    ]
    assert len(suppressed) == 1
    assert suppressed[0]["kind"] == "system"
    assert suppressed[0]["bridge"][0] == {
        "reason": "most_specific_rule_wins",
        "target": "notify.mobile_app_pixel",
        "event": "any_change",
    }

    await call(hass, "set_mode", {"mode": "away"})
    await call(hass, "set_mode", {"mode": "home"})
    await call(hass, "set_mode", {"mode": "away"})  # duplicate within 10 s
    await hass.async_block_till_done()
    reasons = [
        e["bridge"][0]["reason"]
        for e in entry.runtime_data.history.entries
        if e["rule"] == "notification_suppressed"
    ]
    assert reasons == ["most_specific_rule_wins", "rate_limited"]


def _companion_entity(hass: HomeAssistant, device_name: str = "Pixel 9") -> str:
    """Register a mobile_app notify entity the way the Companion app integration does."""
    entry = MockConfigEntry(
        domain="mobile_app", data={"device_name": device_name, "webhook_id": "hook123"}
    )
    entry.add_to_hass(hass)
    return (
        er.async_get(hass)
        .async_get_or_create("notify", "mobile_app", "dev-1", config_entry=entry)
        .entity_id
    )


async def test_companion_entity_target_keeps_the_channel(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A Companion app notify entity goes through its mobile_app service with HM_ channel data.

    notify.send_message cannot carry data, so the phone would use its default "General"
    channel; the device's mobile_app_<name> service is used instead.
    """
    entity_id = _companion_entity(hass)
    phone = async_mock_service(hass, "notify", "mobile_app_pixel_9")
    sent = async_mock_service(hass, "notify", "send_message")
    await setup_entry(hass, freezer, _opts({"event": "any_change", "targets": [entity_id]}))
    await call(hass, "set_mode", {"mode": "night"})
    await hass.async_block_till_done()
    assert not sent
    assert len(phone) == 1
    data = phone[0].data["data"]
    assert data["channel"] == data["group"] == CHANNEL_MODE_CHANGES
    assert data["push"] == {"interruption-level": "passive"}


async def test_companion_entity_falls_back_to_the_platform_service(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without the per-device service, notify.mobile_app is called with the webhook target."""
    entity_id = _companion_entity(hass, "Unmatched")
    platform = async_mock_service(hass, "notify", "mobile_app")
    await setup_entry(hass, freezer, _opts({"event": "denied", "targets": [entity_id]}))
    hass.bus.async_fire("home_modes_denied", {"role": "away", "reason": "not_allowed"})
    await hass.async_block_till_done()
    assert platform[0].data["target"] == ["hook123"]
    assert platform[0].data["data"]["channel"] == CHANNEL_ALERTS
