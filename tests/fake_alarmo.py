"""A minimal stand-in for Alarmo: one alarm entity plus alarmo.arm / alarmo.disarm.

It mirrors what Alarmo does that matters for the bridge: instant arm keeps the caller's
Context on the state write, an exit delay goes through "arming" (with a "delay"
attribute) and the final armed state is written later WITHOUT the caller's Context.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant, ServiceCall

ENTITY = "alarm_control_panel.alarmo"
MODES = {
    "home": "armed_home",
    "away": "armed_away",
    "night": "armed_night",
    "vacation": "armed_vacation",
    "custom": "armed_custom_bypass",
}


class FakeAlarmo:
    """Fake Alarmo."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        state: str = "disarmed",
        exit_delay: float = 0,
        code: bool = False,
    ) -> None:
        """Create the entity state and register the services."""
        self.hass = hass
        self.exit_delay = exit_delay
        self.code = code
        self.calls: list[tuple[str, dict[str, Any], Context]] = []
        self.pending: str | None = None
        self.set(state)
        hass.services.async_register("alarmo", "arm", self._arm)
        hass.services.async_register("alarmo", "disarm", self._disarm)

    def set(self, state: str, context: Context | None = None, **attrs: Any) -> None:
        """Write the alarm state (a keypad press or Alarmo's own transition)."""
        attributes = {"code_format": "number" if self.code else None, **attrs}
        self.hass.states.async_set(ENTITY, state, attributes, context=context)

    async def _arm(self, call: ServiceCall) -> None:
        self.calls.append(("arm", dict(call.data), call.context))
        target = MODES[call.data["mode"]]
        if self.exit_delay:
            self.pending = target
            self.set("arming", call.context, delay=self.exit_delay)
        else:
            self.set(target, call.context)

    async def _disarm(self, call: ServiceCall) -> None:
        self.calls.append(("disarm", dict(call.data), call.context))
        self.set("disarmed", call.context)

    def finish_arming(self) -> None:
        """The exit delay is over: Alarmo writes the final state with a fresh Context."""
        assert self.pending is not None
        target, self.pending = self.pending, None
        self.set(target, Context())

    def remove(self) -> None:
        """Simulate removing Alarmo at runtime."""
        self.hass.states.async_remove(ENTITY)
        self.hass.services.async_remove("alarmo", "arm")
        self.hass.services.async_remove("alarmo", "disarm")

    @property
    def arm_calls(self) -> list[dict[str, Any]]:
        """Return the data of all alarmo.arm calls."""
        return [data for name, data, _ in self.calls if name == "arm"]
