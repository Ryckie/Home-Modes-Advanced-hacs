"""Presence tracking, away/vacation timers and arrival rules."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.home_modes.presence import PresenceTracker

from .helpers import advance, data, presence_options, primary, roles_without, setup_entry

HOME2 = {"person.anna": "home", "person.ben": "home"}


async def test_tracker_values_and_unknown_handling(hass: HomeAssistant) -> None:
    """Unknown/unavailable never change the last known status."""
    tracker = PresenceTracker(hass, ["person.a", "person.b"])
    calls: list[int] = []
    remove = tracker.async_add_listener(lambda: calls.append(1))
    hass.states.async_set("person.a", "home")
    tracker.async_start()
    assert (tracker.all_home, tracker.all_away) == (None, False)  # b never known
    hass.states.async_set("person.b", "home")
    await hass.async_block_till_done()
    assert (tracker.all_home, tracker.all_away) == (True, False)
    hass.states.async_set("person.b", "unavailable")
    hass.states.async_set("person.a", "unknown")
    await hass.async_block_till_done()
    assert (tracker.all_home, tracker.all_away) == (True, False)  # unchanged
    hass.states.async_set("person.a", "work")  # a zone name counts as away
    await hass.async_block_till_done()
    assert (tracker.all_home, tracker.all_away) == (False, False)
    hass.states.async_set("person.b", "not_home")
    await hass.async_block_till_done()
    assert (tracker.all_home, tracker.all_away) == (False, True)
    hass.states.async_remove("person.b")  # removed entity: keep last status
    await hass.async_block_till_done()
    assert tracker.all_away is True
    assert len(calls) == 4
    remove()
    remove()  # removing twice is harmless
    tracker.async_stop()
    tracker.async_stop()


async def test_tracker_without_persons(hass: HomeAssistant) -> None:
    """No tracked persons: both signals stay unknown."""
    tracker = PresenceTracker(hass, [])
    tracker.async_start()
    assert (tracker.all_home, tracker.all_away) == (None, None)


async def test_away_after_delay(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Everybody away for the delay -> away (all_away disabled -> away role)."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    assert data(entry).all_away_since is not None
    await advance(hass, freezer, minutes=3)
    assert primary(entry) == "home"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "away"
    assert data(entry).last_trigger.source == "presence"
    assert data(entry).last_trigger.rule == "presence_away"
    assert hass.states.get("sensor.home_mode_trigger_reason").attributes["rule"] == "presence_away"


async def test_away_cancelled_when_someone_returns(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A person arriving before the delay cancels the away timer."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, minutes=2)
    hass.states.async_set("person.anna", "home")
    await hass.async_block_till_done()
    assert data(entry).all_away_since is None
    await advance(hass, freezer, minutes=10)
    assert primary(entry) == "home"


async def test_all_away_role_used_when_enabled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With the all_away role enabled the delay leads to all_away, not away."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2, derived=True)
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "all_away"
    assert hass.states.get("binary_sensor.home_mode_all_away").state == "on"
    assert hass.states.get("binary_sensor.home_mode_all_home").state == "off"


async def test_vacation_after_hours_and_cancellation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Vacation follows continuous all_away; a return resets the vacation clock."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"
    await advance(hass, freezer, hours=23)
    assert primary(entry) == "away"
    hass.states.async_set("person.ben", "home")  # return: back home, clocks reset
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert data(entry).last_trigger.rule == "presence_arrival"
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=23, minutes=59)
    assert primary(entry) == "away"
    await advance(hass, freezer, minutes=2)
    assert primary(entry) == "vacation"
    assert data(entry).last_trigger.rule == "presence_vacation"


async def test_vacation_disabled_stays_away(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Vacation is entered only if the vacation role is enabled."""
    roles = roles_without("vacation")
    entry = await setup_entry(hass, freezer, {**presence_options(), "roles": roles}, states=HOME2)
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=30)
    assert primary(entry) == "away"


async def test_arrival_goes_home_from_away_and_vacation(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The first person arriving from all_away/vacation goes to home."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=25)
    assert primary(entry) == "vacation"
    hass.states.async_set("person.anna", "home")
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert data(entry).last_trigger.source == "presence"


async def test_arrival_with_home_disabled_does_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Arrival goes home only if the home role is enabled."""
    entry = await setup_entry(
        hass,
        freezer,
        {**presence_options(), "roles": roles_without("home")},
        states=HOME2,
    )
    assert primary(entry) == "night"  # first enabled primary
    hass.states.async_set("person.anna", "not_home")
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"
    hass.states.async_set("person.anna", "home")
    await hass.async_block_till_done()
    assert primary(entry) == "away"


async def test_all_home_rule(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """home -> all_home when everybody is home; back to home when somebody leaves."""
    entry = await setup_entry(
        hass,
        freezer,
        presence_options(),
        states={"person.anna": "home", "person.ben": "not_home"},
        derived=True,
    )
    assert primary(entry) == "home"
    hass.states.async_set("person.ben", "home")
    await hass.async_block_till_done()
    assert primary(entry) == "all_home"
    assert data(entry).last_trigger.rule == "presence_all_home"
    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    assert primary(entry) == "home"
    assert data(entry).last_trigger.rule == "presence_all_home_end"


async def test_unknown_and_unavailable_do_not_trigger(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Unknown/unavailable states are 'not changed': no away, no arrival."""
    entry = await setup_entry(hass, freezer, presence_options(), states=HOME2)
    hass.states.async_set("person.anna", "unavailable")
    hass.states.async_set("person.ben", "unknown")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=48)
    assert primary(entry) == "home"
    assert data(entry).all_away_since is None
    # Only one person known away while the other is unknown: not all away.
    # Anna leaves, Ben's last known status is still home: not all away.
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, hours=48)
    assert primary(entry) == "home"
    assert data(entry).all_away_since is None


async def test_unknown_at_startup_then_known(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Persons unknown at startup become known later and then count."""
    entry = await setup_entry(hass, freezer, presence_options(["person.anna"]))
    assert data(entry).all_away_since is None
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    await advance(hass, freezer, minutes=5)
    assert primary(entry) == "away"
