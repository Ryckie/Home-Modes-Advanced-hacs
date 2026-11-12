"""No secrets, full notification targets or message bodies reach the log at any level."""

from __future__ import annotations

import contextlib
import logging

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .helpers import advance, call, setup_entry

BODY = "BODY-9f3c-private-text"
TARGET = "mobile_app_private_phone_77"
SECRET = "CODE-1234-secret"


async def test_log_has_no_targets_bodies_or_codes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog, guest_user
) -> None:
    """Run notifications (one failing), a denied guest, template errors and actions at DEBUG."""
    caplog.set_level(logging.DEBUG, logger="custom_components.home_modes")

    async def broken(call: ServiceCall) -> None:
        # a failing notify service whose error text repeats the message body
        raise HomeAssistantError(f"cannot deliver {call.data.get('message')} {SECRET}")

    hass.services.async_register("notify", TARGET, broken)
    await setup_entry(
        hass,
        freezer,
        {
            "notify": {
                "rules": [
                    {
                        "event": "any_change",
                        "services": [TARGET],
                        "message": f"{BODY} {{{{ to }}}}",
                    },
                    {"event": "denied", "services": [TARGET], "message": "{{ unknown_fn( }}"},
                ],
                "rate_limit_s": 0,
            },
            "user_rules": {guest_user.id: {"mode": "allow_list", "roles": ["home"]}},
        },
    )
    await call(hass, "set_mode", {"mode": "night"})
    with contextlib.suppress(Exception):
        await call(hass, "set_mode", {"mode": "away"}, user_id=guest_user.id)
    await advance(hass, freezer, seconds=30)
    await hass.async_block_till_done()

    # Only this integration's own records: Home Assistant core logs a failing foreign
    # service (the test's own notify service) with its traceback, which is outside our control.
    ours = "\n".join(
        record.getMessage() + (record.exc_text or "")
        for record in caplog.records
        if record.name.startswith("custom_components.home_modes")
    )
    assert "failed" in ours  # the failures were logged ...
    for forbidden in (BODY, TARGET, SECRET):
        assert forbidden not in ours, forbidden  # ... without the details
