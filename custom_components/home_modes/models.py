"""Data models for Home Modes Advanced."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol

from homeassistant.core import CALLBACK_TYPE, Context
from homeassistant.util import dt as dt_util

from .const import CUSTOM_PREFIX


class RoleType(StrEnum):
    """Base type of a role."""

    HOME = "home"
    NIGHT = "night"
    AWAY = "away"
    VACATION = "vacation"
    GUEST = "guest"
    DND = "dnd"
    CUSTOM = "custom"
    ALL_HOME = "all_home"
    ALL_AWAY = "all_away"


class RoleKind(StrEnum):
    """How a role behaves."""

    PRIMARY = "primary"
    OVERLAY = "overlay"
    DERIVED = "derived"


ROLE_KINDS: Final = MappingProxyType(
    {
        RoleType.HOME: RoleKind.PRIMARY,
        RoleType.NIGHT: RoleKind.PRIMARY,
        RoleType.AWAY: RoleKind.PRIMARY,
        RoleType.VACATION: RoleKind.PRIMARY,
        RoleType.CUSTOM: RoleKind.PRIMARY,
        RoleType.GUEST: RoleKind.OVERLAY,
        RoleType.DND: RoleKind.OVERLAY,
        RoleType.ALL_HOME: RoleKind.DERIVED,
        RoleType.ALL_AWAY: RoleKind.DERIVED,
    }
)


class ChangeSource(StrEnum):
    """Where a change request comes from."""

    MANUAL = "manual"
    SCHEDULE = "schedule"
    SENSOR = "sensor"
    PRESENCE = "presence"
    ALARMO = "alarmo"
    EXPIRY = "temporary_expiry"
    SYSTEM = "system"


# Single place to change source priorities. Lower number = higher priority.
# SYSTEM (rank 0) is used for internal housekeeping and bypasses override checks.
SOURCE_RANKS: Final[Mapping[ChangeSource, int]] = MappingProxyType(
    {
        ChangeSource.SYSTEM: 0,
        ChangeSource.MANUAL: 1,
        ChangeSource.ALARMO: 1,
        ChangeSource.EXPIRY: 1,
        ChangeSource.SCHEDULE: 2,
        ChangeSource.SENSOR: 3,
        ChangeSource.PRESENCE: 4,
    }
)


class ChangeKind(StrEnum):
    """Kind of change."""

    PRIMARY = "primary"
    OVERLAY = "overlay"


class ChangeStatus(StrEnum):
    """Outcome of a change request."""

    APPLIED = "applied"
    UNCHANGED = "unchanged"
    DENIED = "denied"
    IGNORED = "ignored"
    REJECTED = "rejected"
    DEFERRED = "deferred"  # requested from inside the pipeline; applied right after it


class PipelineStage(StrEnum):
    """Hook points that later steps register into, in execution order."""

    EXIT_ACTIONS = "exit_actions"  # before the state is changed
    ENTER_ACTIONS = "enter_actions"  # after the state is changed
    HISTORY = "history"  # after the event is fired
    NOTIFY = "notify"
    ALARMO = "alarmo"


def role_type_from_id(role_id: str) -> RoleType:
    """Return the role type for a role id (custom_1 -> CUSTOM)."""
    if role_id.startswith(CUSTOM_PREFIX) and role_id[len(CUSTOM_PREFIX) :].isdigit():
        return RoleType.CUSTOM
    return RoleType(role_id)


@dataclass(frozen=True, slots=True)
class Role:
    """A configured role (mode)."""

    id: str
    name: str
    enabled: bool = True
    enter_actions: tuple[dict[str, Any], ...] = ()
    exit_actions: tuple[dict[str, Any], ...] = ()

    @property
    def type(self) -> RoleType:
        """Return the base type."""
        return role_type_from_id(self.id)

    @property
    def kind(self) -> RoleKind:
        """Return the kind."""
        return ROLE_KINDS[self.type]

    @property
    def selectable_primary(self) -> bool:
        """Return True if the role can be the primary mode."""
        return self.kind is not RoleKind.OVERLAY

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Role:
        """Parse a stored role. Unknown keys are ignored."""
        role_id = str(data["id"])
        role_type_from_id(role_id)  # raises ValueError for unknown ids
        return cls(
            id=role_id,
            name=str(data["name"]),
            enabled=bool(data.get("enabled", True)),
            enter_actions=tuple(dict(a) for a in data.get("enter_actions") or ()),
            exit_actions=tuple(dict(a) for a in data.get("exit_actions") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in the config entry options."""
        data: dict[str, Any] = {"id": self.id, "name": self.name, "enabled": self.enabled}
        if self.enter_actions:
            data["enter_actions"] = [dict(a) for a in self.enter_actions]
        if self.exit_actions:
            data["exit_actions"] = [dict(a) for a in self.exit_actions]
        return data


def validate_roles(roles: list[Role]) -> str | None:
    """Return an error key if the role list is invalid, else None."""
    names = [role.name.strip().casefold() for role in roles]
    if any(not name for name in names):
        return "name_required"
    if len(set(names)) != len(names):
        return "name_exists"
    if not any(r.enabled and r.kind is RoleKind.PRIMARY for r in roles):
        return "no_primary"
    return None


class OverrideMode(StrEnum):
    """How an override ends."""

    TIMED = "timed"  # ends at an absolute time (end of day, duration, temporary)
    NEXT_AUTO = "next_auto"  # ends when the next auto-rule trigger would fire
    SET_AUTO = "set_auto"  # ends only when set_auto is called


@dataclass(frozen=True, slots=True)
class Override:
    """A manual override that blocks lower priority sources."""

    set_by: str
    until: datetime | None = None
    mode: OverrideMode = OverrideMode.TIMED

    def is_active(self, now: datetime) -> bool:
        """Return True if the override is still in effect."""
        return self.until is None or self.until > now

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "set_by": self.set_by,
            "until": self.until.isoformat() if self.until else None,
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Override:
        """Deserialize."""
        until = dt_util.parse_datetime(data["until"]) if data.get("until") else None
        return cls(
            set_by=str(data["set_by"]),
            until=until,
            mode=OverrideMode(data.get("mode", OverrideMode.TIMED)),
        )


@dataclass(frozen=True, slots=True)
class Temporary:
    """A temporary mode that reverts to a stored mode at an absolute time."""

    revert_to: str
    until: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {"revert_to": self.revert_to, "until": self.until.isoformat()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Temporary:
        """Deserialize."""
        until = dt_util.parse_datetime(data["until"])
        if until is None:
            raise ValueError("invalid until")
        return cls(revert_to=str(data["revert_to"]), until=until)


@dataclass(frozen=True, slots=True)
class TriggerInfo:
    """What caused the last primary mode change."""

    source: str
    rule: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {"source": self.source, "rule": self.rule}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TriggerInfo:
        """Deserialize."""
        return cls(source=str(data["source"]), rule=data.get("rule"))


@dataclass(frozen=True, slots=True)
class HomeModesState:
    """Runtime state, restored on restart."""

    primary: str
    since: datetime
    previous: str | None = None
    overlays: tuple[str, ...] = ()
    override: Override | None = None
    last_trigger: TriggerInfo | None = None
    auto_enabled: bool = True
    temporary: Temporary | None = None
    all_away_since: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "primary": self.primary,
            "previous": self.previous,
            "since": self.since.isoformat(),
            "overlays": list(self.overlays),
            "override": self.override.to_dict() if self.override else None,
            "last_trigger": self.last_trigger.to_dict() if self.last_trigger else None,
            "auto_enabled": self.auto_enabled,
            "temporary": self.temporary.to_dict() if self.temporary else None,
            "all_away_since": self.all_away_since.isoformat() if self.all_away_since else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HomeModesState:
        """Deserialize. Raises KeyError/ValueError/TypeError on corrupt data."""
        since = dt_util.parse_datetime(data["since"])
        if since is None:
            raise ValueError("invalid since")
        return cls(
            primary=str(data["primary"]),
            previous=data.get("previous"),
            since=since,
            overlays=tuple(str(o) for o in data.get("overlays", [])),
            override=Override.from_dict(data["override"]) if data.get("override") else None,
            last_trigger=TriggerInfo.from_dict(data["last_trigger"])
            if data.get("last_trigger")
            else None,
            auto_enabled=bool(data.get("auto_enabled", True)),
            temporary=Temporary.from_dict(data["temporary"]) if data.get("temporary") else None,
            all_away_since=dt_util.parse_datetime(data["all_away_since"])
            if data.get("all_away_since")
            else None,
        )


@dataclass(frozen=True, slots=True)
class ChangeRequest:
    """A request to change a role."""

    role: str
    source: ChangeSource
    rule: str | None = None
    context: Context | None = None
    active: bool = True  # only meaningful for overlays
    override: bool | None = None  # None: start an override if a user is present
    temporary_until: datetime | None = None  # set by set_temporary


@dataclass(frozen=True, slots=True)
class AutoCandidate:
    """An auto-rule that wants to change the primary mode."""

    source: ChangeSource
    rule: str
    role: str


@dataclass(frozen=True, slots=True)
class Change:
    """An applied change, passed to pipeline hooks."""

    kind: ChangeKind
    role: str
    from_role: str | None
    to_role: str | None
    source: ChangeSource
    rule: str | None
    user_id: str | None
    context: Context | None
    at: datetime
    # Notes added by hooks (action failures, bridge notes); read by the history hook.
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChangeResult:
    """Outcome of a change request."""

    status: ChangeStatus
    reason: str | None = None
    change: Change | None = None


class StageHook(Protocol):
    """A callable registered into a pipeline stage."""

    async def __call__(self, change: Change) -> None:
        """Run the hook for an applied change."""


class PresenceProvider(Protocol):
    """Reports household presence."""

    @property
    def all_home(self) -> bool | None:
        """Return True if everybody is home, None if unknown."""

    @property
    def all_away(self) -> bool | None:
        """Return True if everybody is away, None if unknown."""

    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Register a callback for presence changes, return an unsubscribe."""


class UnknownPresenceProvider:
    """Presence provider that always reports unknown (no persons tracked)."""

    @property
    def all_home(self) -> bool | None:
        """Return unknown."""
        return None

    @property
    def all_away(self) -> bool | None:
        """Return unknown."""
        return None

    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Register a listener (never called)."""
        return lambda: None
