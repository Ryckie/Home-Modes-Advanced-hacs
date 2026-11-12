"""Enter and exit actions of roles.

Each action of a role runs as its own script (helpers.script) so that one failing or
slow action never stops the others and never blocks or reverts the mode change.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script

from .const import DOMAIN
from .coordinator import HomeModesCoordinator
from .engine import ChangeEngine
from .models import Change, PipelineStage
from .template_vars import role_name, role_variables

_LOGGER = logging.getLogger(__name__)

PHASE_EXIT = "exit"
PHASE_ENTER = "enter"
NOTE_FAILURES = "action_failures"


class ActionRunner:
    """Runs the enter/exit actions of roles through the change pipeline."""

    def __init__(
        self, hass: HomeAssistant, coordinator: HomeModesCoordinator, engine: ChangeEngine
    ) -> None:
        """Initialize the runner."""
        self.hass = hass
        self.coordinator = coordinator
        self.engine = engine

    def async_register(self) -> list[Any]:
        """Register the pipeline hooks. Returns the unregister callbacks."""
        return [
            self.engine.async_register_hook(PipelineStage.EXIT_ACTIONS, self._async_exit),
            self.engine.async_register_hook(PipelineStage.ENTER_ACTIONS, self._async_enter),
        ]

    async def _async_exit(self, change: Change) -> None:
        # Leaving a role: primary change from A, or an overlay being turned off.
        if change.from_role is not None and change.to_role != change.from_role:
            await self._async_run_role(change, change.from_role, PHASE_EXIT)

    async def _async_enter(self, change: Change) -> None:
        if change.to_role is not None and change.from_role != change.to_role:
            await self._async_run_role(change, change.to_role, PHASE_ENTER)

    async def _async_run_role(self, change: Change, role_id: str, phase: str) -> None:
        role = self.coordinator.role(role_id)
        if role is None:
            return
        actions = role.exit_actions if phase == PHASE_EXIT else role.enter_actions
        if not actions:
            return
        timeout = self.coordinator.integrations.actions_timeout
        variables = {
            **role_variables(self.coordinator, change.from_role, change.to_role),
            "role": change.role,
            "role_name": role_name(self.coordinator, change.role),
            "phase": phase,
            "source": change.source.value,
            "rule": change.rule,
            "user_id": change.user_id,
        }
        # A context that is a child of the change's context; changes requested with it
        # (or with a context whose parent it is) are recognised as action-triggered.
        parent_id = change.context.id if change.context else None
        for index, action in enumerate(actions, start=1):
            context = Context(parent_id=parent_id)
            self.engine.action_context_ids.add(context.id)
            try:
                await self._async_run_action(action, variables, context, timeout)
            except TimeoutError:
                self._failure(change, role_id, phase, index, f"timeout after {timeout:g} s")
            except Exception as err:
                self._failure(
                    change, role_id, phase, index, f"{type(err).__name__}: {str(err)[:200]}"
                )
            finally:
                self.engine.action_context_ids.discard(context.id)

    async def _async_run_action(
        self, action: dict[str, Any], variables: dict[str, Any], context: Context, timeout: float
    ) -> None:
        script = Script(
            self.hass,
            cv.SCRIPT_SCHEMA([action]),  # compiles templates; invalid actions fail here
            f"{DOMAIN} action",
            DOMAIN,
            script_mode="single",
            logger=_LOGGER,
        )
        try:
            async with asyncio.timeout(timeout):
                await script.async_run(variables, context)
        except TimeoutError:
            await script.async_stop()
            raise

    @staticmethod
    def _failure(change: Change, role_id: str, phase: str, index: int, error: str) -> None:
        _LOGGER.warning(
            "%s action %s of role %s failed (the mode change is not affected): %s",
            phase,
            index,
            role_id,
            error,
        )
        change.notes.setdefault(NOTE_FAILURES, []).append(
            {"role": role_id, "phase": phase, "index": index, "error": error}
        )
