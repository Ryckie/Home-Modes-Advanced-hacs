"""Optional two-way bridge between Home Modes and Alarmo.

Alarmo is never required: the bridge only talks to the Alarmo alarm entity and to
Alarmo's own services, and every call is guarded so that a missing or removed Alarmo
only produces a bridge error (once per outage), never a failure of Home Modes.

Loop guard (Alarmo's own ``context_id`` is an internal integer, not a Home Assistant
Context, and entity state writes only keep the caller's Context for ~5 s):
  1. origin tag: changes made by the bridge itself carry source ``alarmo`` and are never
     sent back to Alarmo;
  2. context ids of our own service calls are remembered (works for instant transitions);
  3. expected-state suppression: after asking Alarmo to reach state X, the next final
     state X seen within a short window (extended by Alarmo's exit delay) is our own echo.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .coordinator import HomeModesCoordinator
from .engine import ChangeEngine
from .models import Change, ChangeKind, ChangeRequest, ChangeSource, PipelineStage
from .settings import ALARMO_ARM_MODES, ALARMO_STATES, AlarmoMapping, AlarmoSettings

if TYPE_CHECKING:
    from .history import HistoryLog
    from .notify import Notifier

_LOGGER = logging.getLogger(__name__)

ALARMO_DOMAIN = "alarmo"
SERVICE_ARM = "arm"
SERVICE_DISARM = "disarm"
EVENT_FAILED_TO_ARM = "alarmo_failed_to_arm"
INSTANT_WINDOW = timedelta(seconds=15)  # how long we wait for Alarmo to react
ARMING_GRACE = timedelta(seconds=10)  # added to Alarmo's exit delay
BUSY_STATES = frozenset({"arming", "pending", "triggered", "disarming"})

ERR_NOT_FOUND = "alarmo_not_found"
ERR_UNAVAILABLE = "alarmo_unavailable"
ERR_SERVICE = "alarmo_service_missing"
ERR_CODE = "code_required"
ERR_CALL = "alarmo_call_failed"
ERR_FAILED_TO_ARM = "failed_to_arm"


@dataclass(slots=True)
class _Expected:
    state: str
    expires: datetime


class AlarmoBridge:
    """Maps Alarmo states to roles and back."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HomeModesCoordinator,
        engine: ChangeEngine,
        history: HistoryLog,
        notifier: Notifier,
    ) -> None:
        """Initialize the bridge."""
        self.hass = hass
        self.coordinator = coordinator
        self.engine = engine
        self.history = history
        self.notifier = notifier
        self._unsubs: list[Callable[[], None]] = []
        self._own_contexts: deque[str] = deque(maxlen=20)
        self._expected: _Expected | None = None
        self._reported: set[str] = set()

    @property
    def _cfg(self) -> AlarmoSettings:
        return self.coordinator.integrations.alarmo

    @callback
    def async_setup(self) -> None:
        """Start the bridge (nothing happens while it is disabled)."""
        if not self._cfg.enabled:
            return
        direction = self._cfg.direction
        if direction in ("both", "to_alarmo"):
            self._unsubs.append(
                self.engine.async_register_hook(PipelineStage.ALARMO, self._on_change)
            )
        if direction in ("both", "from_alarmo"):
            self._unsubs.append(
                self.hass.bus.async_listen(
                    EVENT_STATE_CHANGED, self._on_state, event_filter=self._state_filter
                )
            )
        self._unsubs.append(self.hass.bus.async_listen(EVENT_FAILED_TO_ARM, self._on_failed))
        if self.entity_id is None:
            _LOGGER.info("Alarmo bridge enabled but no Alarmo entity found yet; waiting for it")

    @callback
    def async_unload(self) -> None:
        """Stop the bridge."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # --- entity -------------------------------------------------------------

    @property
    def entity_id(self) -> str | None:
        """Return the configured Alarmo entity, else the only Alarmo alarm panel."""
        if self._cfg.entity_id:
            return self._cfg.entity_id
        registry = er.async_get(self.hass)
        found = [
            e.entity_id
            for e in registry.entities.values()
            if e.platform == ALARMO_DOMAIN and e.domain == "alarm_control_panel"
        ]
        return found[0] if len(found) == 1 else None

    @callback
    def _state_filter(self, data: EventStateChangedData) -> bool:
        entity_id = self.entity_id
        return entity_id is not None and data["entity_id"] == entity_id

    # --- Alarmo -> Home Modes ----------------------------------------------

    def _mapping_for_state(self, state: str) -> AlarmoMapping | None:
        return next((m for m in self._cfg.mappings if m.state == state), None)

    def _mapping_for_role(self, role: str) -> AlarmoMapping | None:
        return next((m for m in self._cfg.mappings if m.role == role and m.to_alarmo), None)

    async def _on_state(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        old = event.data["old_state"]
        if new is None:
            return  # entity removed: nothing to do
        state = new.state
        if state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        self._reported.clear()  # Alarmo is reachable again
        now = dt_util.utcnow()
        self._extend_expectation(new.state, new.attributes, now)
        if state not in ALARMO_STATES:
            return  # arming / pending / triggered are transitions, not target states
        if old is not None and old.state == state:
            return  # attribute-only update
        if self._is_failed_arm(state, new.attributes, now):
            return
        if self._is_echo(new.context, state, now):
            _LOGGER.debug("Ignoring Alarmo state %s: caused by the bridge itself", state)
            return
        mapping = self._mapping_for_state(state)
        if mapping is None or not mapping.from_alarmo or not mapping.role:
            return
        role = self.coordinator.role(mapping.role)
        if role is None or not role.enabled:
            self.history.async_add_system(
                "bridge_note", {"note": "mapped_role_unavailable", "state": state}
            )
            return
        await self.engine.async_change(
            ChangeRequest(
                mapping.role,
                ChangeSource.ALARMO,
                rule=f"alarmo:{state}",
                context=new.context,
                override=True,
            )
        )

    def _is_failed_arm(self, state: str, attrs: Any, now: datetime) -> bool:
        """Return True (and report it) if this state is Alarmo undoing our failed arm.

        When open sensors block arming, Alarmo first writes the previous state back and only
        then fires alarmo_failed_to_arm. That write carries the blocking sensors in
        "open_sensors"; a person disarming at the panel or keypad clears them. The revert is
        not a user action, so it must not change the mode.
        """
        expected = self._expected
        if expected is None or now >= expected.expires or state == expected.state:
            return False
        open_sensors = attrs.get("open_sensors")
        if not open_sensors:
            return False
        self._expected = None  # the event that follows is then ignored (no double report)
        count = len(open_sensors) if isinstance(open_sensors, dict | list) else 1
        self._notes_error(None, ERR_FAILED_TO_ARM, f"open_sensors ({count})")
        return True

    def _is_echo(self, context: Context, state: str, now: datetime) -> bool:
        if context.id in self._own_contexts or context.parent_id in self._own_contexts:
            return True
        expected = self._expected
        if expected is None:
            return False
        self._expected = None  # a final state always ends the expectation
        return expected.state == state and now < expected.expires

    def _extend_expectation(self, state: str, attrs: Any, now: datetime) -> None:
        """While Alarmo counts its exit delay, wait for it before the echo expires."""
        if state != "arming" or self._expected is None or now >= self._expected.expires:
            return
        delay = attrs.get("delay")
        if isinstance(delay, (int, float)) and not isinstance(delay, bool):
            self._expected.expires = now + timedelta(seconds=float(delay)) + ARMING_GRACE

    async def _on_failed(self, event: Event) -> None:
        if self._expected is None:
            return  # not our request (e.g. a keypad press)
        entity_id = event.data.get("entity_id")
        if entity_id not in (None, self.entity_id):
            return
        self._expected = None
        self._notes_error(None, ERR_FAILED_TO_ARM, str(event.data.get("reason") or "unknown"))

    # --- Home Modes -> Alarmo ----------------------------------------------

    async def _on_change(self, change: Change) -> None:
        cfg = self._cfg
        if change.kind is not ChangeKind.PRIMARY or change.to_role is None:
            return
        if change.source in (ChangeSource.ALARMO, ChangeSource.SYSTEM):
            return  # origin guard: never echo Alarmo-originated or startup changes
        if change.source is not ChangeSource.MANUAL and not cfg.apply_auto:
            return  # auto-rule (and expiry) changes never touch Alarmo by default
        mapping = self._mapping_for_role(change.to_role)
        if mapping is None:
            return
        target = mapping.state
        if target == "disarmed":
            if not mapping.allow_disarm:
                self._note(change, "disarm_not_allowed")
                return
            if self._restricted_user(change.user_id):
                self._note(change, "disarm_blocked_for_restricted_user")
                return

        entity_id = self.entity_id
        state = self.hass.states.get(entity_id) if entity_id else None
        if entity_id is None or state is None:
            self._notes_error(change, ERR_NOT_FOUND, "Alarmo entity not found")
            return
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._notes_error(change, ERR_UNAVAILABLE, entity_id)
            return
        self._reported.clear()
        if state.state == target:
            return
        if state.state in BUSY_STATES:
            self._note(change, f"alarm_busy:{state.state}")
            return
        if state.attributes.get("code_format"):
            self._notes_error(change, ERR_CODE, "Alarmo requires a code (never stored here)")
            return
        service = SERVICE_DISARM if target == "disarmed" else SERVICE_ARM
        if not self.hass.services.has_service(ALARMO_DOMAIN, service):
            self._notes_error(change, ERR_SERVICE, f"alarmo.{service} is not available")
            return

        data: dict[str, Any] = {"entity_id": entity_id}
        if target != "disarmed":
            data.update(mode=ALARMO_ARM_MODES[target], skip_delay=False, force=False)
        context = Context(parent_id=change.context.id if change.context else None)
        self._own_contexts.append(context.id)
        self._expected = _Expected(target, dt_util.utcnow() + INSTANT_WINDOW)
        try:
            await self.hass.services.async_call(
                ALARMO_DOMAIN, service, data, blocking=True, context=context
            )
        except Exception as err:
            self._expected = None
            self._notes_error(change, ERR_CALL, f"{type(err).__name__}: {err}")
            return
        self._note(change, f"requested:{target}")

    def _restricted_user(self, user_id: str | None) -> bool:
        rule = self.coordinator.user_rules.get(user_id) if user_id else None
        return rule is not None and rule.mode.value == "allow_list"

    # --- reporting ----------------------------------------------------------

    def _note(self, change: Change, note: str) -> None:
        self.history.async_annotate(change, {"alarmo": note})

    def _notes_error(self, change: Change | None, code: str, detail: str) -> None:
        _LOGGER.warning("Alarmo bridge: %s (%s)", code, detail)
        info = {"error": code, "detail": detail}
        if change is not None:
            self.history.async_annotate(change, info)
        else:
            self.history.async_add_system("bridge_error", info)
        if code not in self._reported:
            self._reported.add(code)
            self.notifier.async_bridge_error(f"{code}: {detail}")
