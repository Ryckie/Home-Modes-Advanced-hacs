"""Temporary migration aid: mirror the active mode to an old input_select.

One direction only (Home Modes -> input_select). Home Modes never reads the
input_select. Off by default. Overlays are written only with the separate
"Mirror overlays" option. Failures are written to the history as system entries.
"""

from __future__ import annotations

import logging

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .coordinator import HomeModesCoordinator
from .engine import ChangeEngine
from .history import HistoryLog
from .models import Change, PipelineStage
from .settings import MirrorSettings

_LOGGER = logging.getLogger(__name__)

RULE_MIRROR_FAILED = "mirror_failed"
REASON_NO_ENTITY = "input_select_missing"
REASON_NO_MAPPING = "no_option_mapped"
REASON_OPTION_MISSING = "option_not_in_input_select"
REASON_CALL_FAILED = "service_call_failed"
# How long a mirror write stays recognised as ours (input_select automations run just after).
GUARD_SECONDS = 5.0


class InputSelectMirror:
    """Writes the matching option to the chosen input_select on every mode change."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HomeModesCoordinator,
        engine: ChangeEngine,
        history: HistoryLog,
    ) -> None:
        """Initialize the mirror."""
        self.hass = hass
        self.coordinator = coordinator
        self.engine = engine
        self.history = history
        self._unsubs: list[CALLBACK_TYPE] = []
        self._guards: dict[str, CALLBACK_TYPE] = {}

    @property
    def _cfg(self) -> MirrorSettings:
        return self.coordinator.integrations.mirror

    @callback
    def async_setup(self) -> None:
        """Register the hook when the mirror is enabled."""
        if self._cfg.enabled and self._cfg.entity_id:
            self._unsubs.append(
                self.engine.async_register_hook(PipelineStage.NOTIFY, self._on_change)
            )

    @callback
    def async_unload(self) -> None:
        """Stop mirroring and drop the loop guards."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in self._guards.values():
            cancel()
        self._guards.clear()

    def _desired_role(self) -> str:
        """Return the role whose option is written.

        "Mirror overlays" off (default): always the primary. On: the most recently
        activated overlay that has an option; with none, the primary. ``state.overlays``
        keeps activation order, so the last mapped entry wins.
        """
        state = self.coordinator.data
        if self._cfg.overlays:
            mapping = self._cfg.mapping
            for overlay_id in reversed(state.overlays):
                if overlay_id in mapping:
                    return overlay_id
        return state.primary

    def _fail(self, reason: str, role_id: str, option: str | None = None) -> None:
        details: dict[str, object] = {"reason": reason, "role": role_id}
        if option is not None:
            details["option"] = option
        _LOGGER.warning("Mirror to input_select failed: %s (role %s)", reason, role_id)
        self.history.async_add_system(RULE_MIRROR_FAILED, details)

    async def _on_change(self, change: Change) -> None:
        cfg = self._cfg
        entity_id = cfg.entity_id
        if entity_id is None:
            return
        role_id = self._desired_role()
        option = cfg.mapping.get(role_id)
        if option is None:
            self._fail(REASON_NO_MAPPING, role_id)
            return
        state = self.hass.states.get(entity_id)
        if state is None:
            self._fail(REASON_NO_ENTITY, role_id, option)
            return
        if option not in (state.attributes.get("options") or []):
            self._fail(REASON_OPTION_MISSING, role_id, option)
            return
        if state.state == option:
            return  # already there: no write, so no state change for anyone to react to
        context = Context(parent_id=change.context.id if change.context else None)
        self._guard(context.id)
        try:
            await self.hass.services.async_call(
                "input_select",
                "select_option",
                {"entity_id": entity_id, "option": option},
                blocking=True,
                context=context,
            )
        except Exception as err:
            self._fail(REASON_CALL_FAILED, role_id, option)
            _LOGGER.debug("Mirror call error: %s", type(err).__name__)

    def _guard(self, context_id: str) -> None:
        """Let the engine treat changes caused by this write like action-triggered ones."""
        self.engine.action_context_ids.add(context_id)

        @callback
        def _release(_now: object) -> None:
            self.engine.action_context_ids.discard(context_id)
            self._guards.pop(context_id, None)

        self._guards[context_id] = async_call_later(self.hass, GUARD_SECONDS, _release)
