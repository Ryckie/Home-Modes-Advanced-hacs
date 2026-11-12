"""Change pipeline for Home Modes Advanced."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from . import permissions
from .const import (
    ACTION_LOOP_MAX,
    ACTION_LOOP_WINDOW,
    DOMAIN,
    EVENT_CHANGED,
    EVENT_DENIED,
    UNTIL_DURATION,
    UNTIL_END_OF_DAY,
    UNTIL_SET_AUTO,
)
from .coordinator import HomeModesCoordinator
from .models import (
    SOURCE_RANKS,
    Change,
    ChangeKind,
    ChangeRequest,
    ChangeResult,
    ChangeSource,
    ChangeStatus,
    HomeModesState,
    Override,
    OverrideMode,
    PipelineStage,
    Role,
    RoleKind,
    StageHook,
    Temporary,
    TriggerInfo,
)

if TYPE_CHECKING:
    from .actions import ActionRunner
    from .alarmo import AlarmoBridge
    from .autorules import AutoRules
    from .history import HistoryLog
    from .mirror import InputSelectMirror
    from .notify import Notifier
    from .vacation import VacationSimulator

_LOGGER = logging.getLogger(__name__)

# Order in which hook stages run around the state change.
_BEFORE_STATE: tuple[PipelineStage, ...] = (PipelineStage.EXIT_ACTIONS,)
_AFTER_STATE: tuple[PipelineStage, ...] = (PipelineStage.ENTER_ACTIONS,)
_AFTER_EVENT: tuple[PipelineStage, ...] = (
    PipelineStage.HISTORY,
    PipelineStage.NOTIFY,
    PipelineStage.ALARMO,
)
# Sources whose primary changes may start an override.
_OVERRIDE_SOURCES: frozenset[ChangeSource] = frozenset({ChangeSource.MANUAL, ChangeSource.ALARMO})


@dataclass
class HomeModesRuntime:
    """Runtime data stored on the config entry."""

    coordinator: HomeModesCoordinator
    engine: ChangeEngine
    rules: AutoRules
    history: HistoryLog
    notifier: Notifier
    bridge: AlarmoBridge
    mirror: InputSelectMirror
    vacation: VacationSimulator
    actions: ActionRunner
    unsubs: list[CALLBACK_TYPE]


type HomeModesConfigEntry = ConfigEntry[HomeModesRuntime]


class ChangeEngine:
    """Single path for every mode change.

    Stages 1-4 (source, permission, priority, role enabled), the state change and
    the event are implemented here. Actions, history, notify and Alarmo are hook
    points that later steps register into with async_register_hook.
    """

    def __init__(self, hass: HomeAssistant, coordinator: HomeModesCoordinator) -> None:
        """Initialize the engine."""
        self.hass = hass
        self.coordinator = coordinator
        self._lock = asyncio.Lock()
        self._hooks: dict[PipelineStage, list[StageHook]] = {stage: [] for stage in PipelineStage}
        # Set by the auto-rule orchestrator: re-evaluates all auto-rules.
        self.evaluator: Callable[[], Awaitable[object]] | None = None
        # Loop protection for changes requested by enter/exit actions.
        self.action_context_ids: set[str] = set()
        self._action_change_times: deque[datetime] = deque()
        self._deferred: set[asyncio.Task[None]] = set()
        # Set by the history log: records a "system" entry (kind, details).
        self.system_log: Callable[[str, dict[str, object]], None] | None = None

    @callback
    def async_register_hook(self, stage: PipelineStage, hook: StageHook) -> CALLBACK_TYPE:
        """Register a hook for a stage. Returns an unregister callback."""
        self._hooks[stage].append(hook)

        @callback
        def _remove() -> None:
            if hook in self._hooks[stage]:
                self._hooks[stage].remove(hook)

        return _remove

    # --- public API ---------------------------------------------------------

    async def async_set_primary(
        self,
        role: str,
        source: ChangeSource,
        *,
        rule: str | None = None,
        context: Context | None = None,
    ) -> ChangeResult:
        """Set the primary mode."""
        return await self.async_change(ChangeRequest(role, source, rule, context))

    async def async_set_overlay(
        self,
        role: str,
        active: bool,
        source: ChangeSource,
        *,
        rule: str | None = None,
        context: Context | None = None,
    ) -> ChangeResult:
        """Turn an overlay on or off."""
        return await self.async_change(ChangeRequest(role, source, rule, context, active))

    async def async_change(self, request: ChangeRequest) -> ChangeResult:
        """Run a change request through the pipeline."""
        context = request.context
        if context is not None and (
            context.id in self.action_context_ids or context.parent_id in self.action_context_ids
        ):
            return self._async_defer(request)
        async with self._lock:
            return await self._async_process(request)

    def _async_defer(self, request: ChangeRequest) -> ChangeResult:
        """Handle a change requested by an enter/exit action of the running change.

        The pipeline lock is held while actions run, so applying it now would deadlock.
        It is applied right after the running change (rate-limited and logged).
        """
        now = dt_util.utcnow()
        while self._action_change_times and now - self._action_change_times[0] > ACTION_LOOP_WINDOW:
            self._action_change_times.popleft()
        if len(self._action_change_times) >= ACTION_LOOP_MAX:
            _LOGGER.warning(
                "Blocked mode change to %s requested by an action: more than %s action-triggered "
                "changes within %s s (possible action loop)",
                request.role,
                ACTION_LOOP_MAX,
                int(ACTION_LOOP_WINDOW.total_seconds()),
            )
            if self.system_log is not None:
                self.system_log("action_loop_blocked", {"role": request.role})
            return ChangeResult(ChangeStatus.REJECTED, "action_loop")
        self._action_change_times.append(now)
        _LOGGER.warning(
            "An action requested a mode change to %s; applying it after the running change",
            request.role,
        )
        task = self.hass.async_create_task(self._async_run_deferred(request))
        self._deferred.add(task)
        task.add_done_callback(self._deferred.discard)
        return ChangeResult(ChangeStatus.DEFERRED)

    async def _async_run_deferred(self, request: ChangeRequest) -> None:
        try:
            async with self._lock:
                await self._async_process(request)
        except Exception:
            _LOGGER.exception("Deferred change to %s failed", request.role)

    @callback
    def async_stop(self) -> None:
        """Cancel deferred changes (on unload)."""
        for task in list(self._deferred):
            task.cancel()

    async def async_set_auto(self, enabled: bool, context: Context | None = None) -> ChangeResult:
        """Set the auto-rules flag (permission checked, not a mode change)."""
        user_id = context.user_id if context else None
        decision = await permissions.async_check_auto_control(
            self.hass, self.coordinator.user_rules, user_id
        )
        if not decision.allowed:
            self._deny(None, user_id, ChangeSource.MANUAL, decision.reason, context)
            return ChangeResult(ChangeStatus.DENIED, decision.reason)
        if self.coordinator.data.auto_enabled == enabled:
            return ChangeResult(ChangeStatus.UNCHANGED)
        self.coordinator.async_set_auto_enabled(enabled)
        if enabled and self.evaluator is not None:
            await self.evaluator()
        return ChangeResult(ChangeStatus.APPLIED)

    async def async_set_temporary(
        self,
        role: str,
        duration: timedelta,
        context: Context | None = None,
    ) -> ChangeResult:
        """Change the mode and revert to the previous mode after the duration."""
        until = dt_util.utcnow() + duration
        return await self.async_change(
            ChangeRequest(role, ChangeSource.MANUAL, "temporary", context, temporary_until=until)
        )

    async def async_revert(self, context: Context | None = None) -> ChangeResult:
        """Go back to the previous mode (manual change), then re-evaluate auto-rules."""
        async with self._lock:
            previous = self.coordinator.data.previous
            if previous is None:
                return ChangeResult(ChangeStatus.REJECTED, "no_previous")
            result = await self._async_process(
                ChangeRequest(previous, ChangeSource.MANUAL, "revert", context)
            )
        if result.status is ChangeStatus.APPLIED:
            await self._async_reevaluate()
        return result

    async def _async_reevaluate(self) -> None:
        """Evaluate auto-rules now (outside the lock), unless the auto switch is off."""
        if self.coordinator.data.auto_enabled and self.evaluator is not None:
            await self.evaluator()

    async def async_set_auto_mode(self, context: Context | None = None) -> ChangeResult:
        """Clear the override and re-evaluate the auto-rules (service set_auto)."""
        user_id = context.user_id if context else None
        decision = await permissions.async_check_auto_control(
            self.hass, self.coordinator.user_rules, user_id
        )
        if not decision.allowed:
            self._deny(None, user_id, ChangeSource.MANUAL, decision.reason, context)
            return ChangeResult(ChangeStatus.DENIED, decision.reason)
        await self.async_clear_override()
        if self.coordinator.data.auto_enabled and self.evaluator is not None:
            await self.evaluator()
        return ChangeResult(ChangeStatus.APPLIED)

    async def async_clear_override(self) -> bool:
        """Clear the override. Returns True if there was one."""
        async with self._lock:
            state = self.coordinator.data
            if state.override is None:
                return False
            self.coordinator.async_apply_state(replace(state, override=None))
            return True

    async def async_expire_temporary(self) -> ChangeResult | None:
        """Revert an expired temporary mode (rank 1, source temporary_expiry).

        Afterwards the auto-rules are re-evaluated (unless the auto switch is off), so
        presence or time conditions that changed meanwhile apply with the normal ranks.
        """
        async with self._lock:
            state = self.coordinator.data
            temporary = state.temporary
            if temporary is None:
                return None
            target = self._fallback_primary(temporary.revert_to)
            if target.id == state.primary:
                self.coordinator.async_apply_state(replace(state, temporary=None, override=None))
                result = ChangeResult(ChangeStatus.UNCHANGED)
            else:
                result = await self._async_process(
                    ChangeRequest(target.id, ChangeSource.EXPIRY, "temporary_expiry")
                )
        await self._async_reevaluate()
        return result

    def _fallback_primary(self, preferred: str | None) -> Role:
        """Return preferred if it is an enabled kind-primary role, else the first one.

        Derived roles (all_home, all_away) are never used as a fallback.
        """
        coordinator = self.coordinator
        role = coordinator.role(preferred) if preferred is not None else None
        if role is not None and role.enabled and role.kind is RoleKind.PRIMARY:
            return role
        first = coordinator.first_enabled_primary()
        if first is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_primary_enabled"
            )
        return first

    async def async_reconcile(self) -> None:
        """Make restored state consistent with the current role configuration.

        If the active primary was removed or disabled, switch to the previous
        enabled primary, else the first enabled primary (source "system").
        Active overlays that are no longer enabled are switched off.
        """
        coordinator = self.coordinator
        state = coordinator.data
        primary = coordinator.role(state.primary)
        if primary is None or not (primary.enabled and primary.selectable_primary):
            target = self._fallback_primary(state.previous)
            await self.async_set_primary(target.id, ChangeSource.SYSTEM, rule="role_disabled")
        for overlay_id in coordinator.data.overlays:
            overlay = coordinator.role(overlay_id)
            if overlay is None:
                coordinator.async_apply_state(
                    replace(
                        coordinator.data,
                        overlays=tuple(o for o in coordinator.data.overlays if o != overlay_id),
                    )
                )
            elif not overlay.enabled:
                await self.async_set_overlay(
                    overlay_id, False, ChangeSource.SYSTEM, rule="role_disabled"
                )

    # --- pipeline -----------------------------------------------------------

    async def _async_process(self, request: ChangeRequest) -> ChangeResult:
        coordinator = self.coordinator
        state = coordinator.data
        context = request.context
        user_id = context.user_id if context else None

        # Stage 2: permission (user sources only; calls without a user are trusted)
        if request.source is ChangeSource.MANUAL and user_id:
            decision = await permissions.async_check_role(
                self.hass, coordinator.user_rules, user_id, request.role
            )
            if not decision.allowed:
                self._deny(request.role, user_id, request.source, decision.reason, context)
                return ChangeResult(ChangeStatus.DENIED, decision.reason)

        # Stage 3: priority
        now = dt_util.utcnow()
        if self._blocked_by_override(state, request.source, now):
            _LOGGER.debug("Ignoring %s change to %s: override active", request.source, request.role)
            return ChangeResult(ChangeStatus.IGNORED, "override_active")

        # Stage 4: target role must exist and be enabled
        role = coordinator.role(request.role)
        if role is None:
            return ChangeResult(ChangeStatus.REJECTED, "unknown_role")
        is_overlay = role.kind is RoleKind.OVERLAY
        if request.active and not role.enabled:
            return ChangeResult(ChangeStatus.REJECTED, "role_disabled")
        if request.temporary_until is not None and is_overlay:
            return ChangeResult(ChangeStatus.REJECTED, "wrong_kind")
        if not is_overlay and not request.active:
            return ChangeResult(ChangeStatus.REJECTED, "cannot_deactivate_primary")

        if is_overlay:
            currently_on = role.id in state.overlays
            if currently_on == request.active:
                return ChangeResult(ChangeStatus.UNCHANGED)
            change = Change(
                kind=ChangeKind.OVERLAY,
                role=role.id,
                from_role=role.id if currently_on else None,
                to_role=role.id if request.active else None,
                source=request.source,
                rule=request.rule,
                user_id=user_id,
                context=context,
                at=now,
            )
        else:
            if state.primary == role.id:
                return ChangeResult(ChangeStatus.UNCHANGED)
            change = Change(
                kind=ChangeKind.PRIMARY,
                role=role.id,
                from_role=state.primary,
                to_role=role.id,
                source=request.source,
                rule=request.rule,
                user_id=user_id,
                context=context,
                at=now,
            )

        # Stage 5/6: exit actions, state, enter actions, event, then late hooks
        await self._run_stages(_BEFORE_STATE, change)
        # Re-read the state: hooks may have awaited and other writers (presence
        # bookkeeping) may have updated it in the meantime.
        coordinator.async_apply_state(self._next_state(coordinator.data, change, request))
        await self._run_stages(_AFTER_STATE, change)
        self.hass.bus.async_fire(
            EVENT_CHANGED,
            {
                "kind": change.kind.value,
                "from": change.from_role,
                "to": change.to_role,
                "role": change.role,
                "active": change.to_role is not None,
                "overlays": list(coordinator.data.overlays),
                "source": change.source.value,
                "rule": change.rule,
                "user_id": change.user_id,
            },
            context=context,
        )
        await self._run_stages(_AFTER_EVENT, change)
        return ChangeResult(ChangeStatus.APPLIED, change=change)

    @staticmethod
    def _blocked_by_override(state: HomeModesState, source: ChangeSource, now: datetime) -> bool:
        override = state.override
        if override is None or source is ChangeSource.SYSTEM:
            return False
        if not override.is_active(now):
            return False
        try:
            override_rank = SOURCE_RANKS[ChangeSource(override.set_by)]
        except ValueError:
            return False
        return SOURCE_RANKS[source] > override_rank

    def _next_state(
        self, state: HomeModesState, change: Change, request: ChangeRequest
    ) -> HomeModesState:
        if change.kind is ChangeKind.OVERLAY:
            overlays = tuple(o for o in state.overlays if o != change.role)
            if change.to_role is not None:
                overlays = (*overlays, change.role)
            return replace(state, overlays=overlays)
        temporary: Temporary | None = None  # any other primary change cancels a temporary
        override = state.override
        if change.source is ChangeSource.EXPIRY:
            override = None
        elif request.temporary_until is not None:
            revert_to = state.temporary.revert_to if state.temporary else state.primary
            temporary = Temporary(revert_to, request.temporary_until)
            override = Override(
                ChangeSource.MANUAL.value, request.temporary_until, OverrideMode.TIMED
            )
        elif change.source in _OVERRIDE_SOURCES:
            wanted = request.override if request.override is not None else bool(change.user_id)
            if wanted:
                override = self._build_override(change.source, change.at)
        return replace(
            state,
            primary=change.role,
            previous=state.primary,
            since=change.at,
            last_trigger=TriggerInfo(change.source.value, change.rule),
            temporary=temporary,
            override=override,
        )

    def _build_override(self, source: ChangeSource, now: datetime) -> Override:
        """Build the override described by the options (override.until)."""
        settings = self.coordinator.settings.override
        if settings.until == UNTIL_END_OF_DAY:
            tomorrow = dt_util.as_local(now).date() + timedelta(days=1)
            return Override(source.value, dt_util.start_of_local_day(tomorrow), OverrideMode.TIMED)
        if settings.until == UNTIL_DURATION:
            return Override(source.value, now + settings.duration, OverrideMode.TIMED)
        if settings.until == UNTIL_SET_AUTO:
            return Override(source.value, None, OverrideMode.SET_AUTO)
        return Override(source.value, None, OverrideMode.NEXT_AUTO)

    async def _run_stages(self, stages: tuple[PipelineStage, ...], change: Change) -> None:
        for stage in stages:
            for hook in list(self._hooks[stage]):
                try:
                    await hook(change)
                except Exception:
                    _LOGGER.exception("Hook for stage %s failed", stage)

    def _deny(
        self,
        role: str | None,
        user_id: str | None,
        source: ChangeSource,
        reason: str,
        context: Context | None,
    ) -> None:
        _LOGGER.warning(
            "Denied change of %s for user %s (%s)", role or "auto switch", user_id, reason
        )
        self.hass.bus.async_fire(
            EVENT_DENIED,
            {"role": role, "user_id": user_id, "source": source.value, "reason": reason},
            context=context,
        )


def raise_for_result(result: ChangeResult, role_name: str) -> None:
    """Raise a translated error for denied or rejected results."""
    if result.status is ChangeStatus.DENIED:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="permission_denied",
            translation_placeholders={"role": role_name},
        )
    if result.status is ChangeStatus.REJECTED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=result.reason or "rejected",
            translation_placeholders={"role": role_name},
        )
