"""Presence tracking for the tracked person entities."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)


class PresenceTracker:
    """Tracks whether the tracked persons are home or away.

    Per person the last known status is kept: True (home), False (away) or None
    (never known). A state of unknown or unavailable (or a missing entity) does
    NOT change the last known status, so it never triggers a change. Any known
    state other than "home" (not_home or a zone name) counts as away.

    all_home is True when every person is known home, False as soon as one
    person is known away, otherwise None. all_away is the mirror image. With no
    tracked persons both are None.
    """

    def __init__(self, hass: HomeAssistant, persons: Iterable[str]) -> None:
        """Initialize the tracker."""
        self.hass = hass
        self._persons = tuple(persons)
        self._status: dict[str, bool | None] = dict.fromkeys(self._persons)
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def persons(self) -> tuple[str, ...]:
        """Return the tracked person entity ids."""
        return self._persons

    @property
    def all_home(self) -> bool | None:
        """Return True if everybody is home, False if somebody is away, else None."""
        values = list(self._status.values())
        if not values:
            return None
        if any(v is False for v in values):
            return False
        return True if all(v is True for v in values) else None

    @property
    def all_away(self) -> bool | None:
        """Return True if everybody is away, False if somebody is home, else None."""
        values = list(self._status.values())
        if not values:
            return None
        if any(v is True for v in values):
            return False
        return True if all(v is False for v in values) else None

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Register a callback called when all_home or all_away changes."""
        self._listeners.append(update_callback)

        @callback
        def _remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    @callback
    def async_start(self) -> None:
        """Read the current states and follow state changes."""
        if self._persons:
            self._unsub = async_track_state_change_event(
                self.hass, list(self._persons), self._handle_event
            )
        self.async_refresh()

    @callback
    def async_stop(self) -> None:
        """Stop following state changes."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def async_refresh(self) -> None:
        """Re-read all person states (used at startup)."""
        before = (self.all_home, self.all_away)
        for entity_id in self._persons:
            state = self.hass.states.get(entity_id)
            self._apply(entity_id, state.state if state else None)
        if (self.all_home, self.all_away) != before:
            self._notify()

    @callback
    def _handle_event(self, event: Event[EventStateChangedData]) -> None:
        before = (self.all_home, self.all_away)
        new_state = event.data["new_state"]
        self._apply(event.data["entity_id"], new_state.state if new_state else None)
        if (self.all_home, self.all_away) != before:
            self._notify()

    def _apply(self, entity_id: str, state: str | None) -> None:
        if state is None or state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return  # keep the last known status
        self._status[entity_id] = state == STATE_HOME

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                _LOGGER.exception("Presence listener failed")
