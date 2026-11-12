"""Persistent history log of mode changes, denied attempts and system events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .actions import NOTE_FAILURES
from .const import DOMAIN, EVENT_DENIED, STORAGE_MINOR_VERSION, STORAGE_SAVE_DELAY, STORAGE_VERSION
from .coordinator import HomeModesCoordinator
from .engine import ChangeEngine
from .models import Change, PipelineStage

_LOGGER = logging.getLogger(__name__)

KIND_PRIMARY = "primary"
KIND_OVERLAY = "overlay"
KIND_DENIED = "denied"
KIND_SYSTEM = "system"
NOTE_ENTRY = "history_entry"


class HistoryLog:
    """Keeps the last N entries in a delayed-save store."""

    def __init__(
        self, hass: HomeAssistant, coordinator: HomeModesCoordinator, engine: ChangeEngine
    ) -> None:
        """Initialize the log."""
        self.hass = hass
        self.coordinator = coordinator
        self.engine = engine
        entry_id = coordinator.config_entry.entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.history",
            minor_version=STORAGE_MINOR_VERSION,
        )
        self._entries: list[dict[str, Any]] = []
        self._unsubs: list[Callable[[], None]] = []

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Return all entries, oldest first."""
        return self._entries

    async def async_setup(self) -> None:
        """Load the stored entries and register the hooks."""
        stored = await self._store.async_load()
        if stored and isinstance(stored.get("entries"), list):
            self._entries = [e for e in stored["entries"] if isinstance(e, dict)]
            self._trim()
        self._unsubs.append(self.engine.async_register_hook(PipelineStage.HISTORY, self._on_change))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_DENIED, self._on_denied))
        self.engine.system_log = self.async_add_system

    async def async_unload(self) -> None:
        """Unregister and write the log immediately."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self.engine.system_log == self.async_add_system:
            self.engine.system_log = None
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"entries": self._entries}

    def _trim(self) -> None:
        limit = self.coordinator.integrations.history_max
        if len(self._entries) > limit:
            del self._entries[: len(self._entries) - limit]

    @callback
    def _append(self, entry: dict[str, Any]) -> dict[str, Any]:
        self._entries.append(entry)
        self._trim()
        self._store.async_delay_save(self._data, STORAGE_SAVE_DELAY)
        return entry

    def _name(self, role_id: str | None) -> str | None:
        if role_id is None:
            return None
        role = self.coordinator.role(role_id)
        return role.name if role else role_id

    async def _user_name(self, user_id: str | None) -> str | None:
        if not user_id:
            return None
        user = await self.hass.auth.async_get_user(user_id)
        return user.name if user and user.name else user_id

    async def _on_change(self, change: Change) -> None:
        entry = {
            "ts": change.at.isoformat(),
            "kind": change.kind.value,
            "from": change.from_role,
            "to": change.to_role,
            "role": change.role,
            "role_name": self._name(change.role),
            "source": change.source.value,
            "rule": change.rule,
            "user_id": change.user_id,
            "user": await self._user_name(change.user_id),
            "action_failures": change.notes.get(NOTE_FAILURES, []),
            "bridge": [],
        }
        change.notes[NOTE_ENTRY] = self._append(entry)

    @callback
    def async_annotate(self, change: Change, note: dict[str, Any]) -> None:
        """Add a bridge note to the entry of a change (written after the change)."""
        entry = change.notes.get(NOTE_ENTRY)
        if entry is None:
            self.async_add_system("bridge_note", note)
            return
        entry["bridge"].append(note)
        self._store.async_delay_save(self._data, STORAGE_SAVE_DELAY)

    async def _on_denied(self, event: Event) -> None:
        data = event.data
        user_id = data.get("user_id")
        self._append(
            {
                "ts": dt_util.utcnow().isoformat(),
                "kind": KIND_DENIED,
                "from": None,
                "to": None,
                "role": data.get("role"),
                "role_name": self._name(data.get("role")),
                "source": data.get("source"),
                "rule": data.get("reason"),
                "user_id": user_id,
                "user": await self._user_name(user_id),
                "action_failures": [],
                "bridge": [],
            }
        )

    @callback
    def async_add_system(self, rule: str, details: dict[str, Any] | None = None) -> None:
        """Add a system entry (vacation simulation start/stop, loop blocked, bridge note)."""
        self._append(
            {
                "ts": dt_util.utcnow().isoformat(),
                "kind": KIND_SYSTEM,
                "from": None,
                "to": None,
                "role": (details or {}).get("role"),
                "role_name": None,
                "source": "system",
                "rule": rule,
                "user_id": None,
                "user": None,
                "action_failures": [],
                "bridge": [details] if details else [],
            }
        )

    async def async_clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()
        await self._store.async_save(self._data())

    def visible_entries(self, limit: int, *, is_admin: bool, user_id: str) -> list[dict[str, Any]]:
        """Return the newest entries the user may see (newest first).

        Admins see everything. Allow-list users (guests) see nothing. Other users see
        mode changes and denied attempts of their own, but no system entries.
        """
        if is_admin:
            visible = self._entries
        else:
            rule = self.coordinator.user_rules.get(user_id)
            if rule is not None and rule.mode.value == "allow_list":
                return []
            visible = [
                e
                for e in self._entries
                if e["kind"] in (KIND_PRIMARY, KIND_OVERLAY)
                or (e["kind"] == KIND_DENIED and e.get("user_id") == user_id)
            ]
        return [self._public(e, is_admin) for e in reversed(visible[-limit:])]

    @staticmethod
    def _public(entry: dict[str, Any], is_admin: bool) -> dict[str, Any]:
        """Return an entry; non-admins do not see action failures or bridge notes."""
        public = dict(entry)
        if not is_admin:
            public["action_failures"] = []
            public["bridge"] = []
        return public
