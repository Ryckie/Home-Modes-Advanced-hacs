"""Switch platform: auto-rules switch and overlay switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEY_AUTO, KEY_ROLE_OVERLAY_SWITCH
from .coordinator import HomeModesCoordinator, HomeModesEntity
from .engine import ChangeEngine, HomeModesConfigEntry, raise_for_result
from .models import ChangeSource, Role


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeModesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the auto switch and one switch per enabled overlay."""
    runtime = entry.runtime_data
    entities: list[SwitchEntity] = [HomeModeAutoSwitch(runtime.coordinator, runtime.engine)]
    entities.extend(
        HomeModeOverlaySwitch(runtime.coordinator, runtime.engine, role)
        for role in runtime.coordinator.overlay_roles
    )
    async_add_entities(entities)


class HomeModeAutoSwitch(HomeModesEntity, SwitchEntity):
    """Enables or disables all auto-rules (turning on re-evaluates immediately)."""

    _attr_translation_key = KEY_AUTO

    def __init__(self, coordinator: HomeModesCoordinator, engine: ChangeEngine) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, KEY_AUTO)
        self._engine = engine

    @property
    def is_on(self) -> bool:
        """Return True if auto-rules are enabled."""
        return self.coordinator.data.auto_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto-rules."""
        raise_for_result(await self._engine.async_set_auto(True, self._context), "auto")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto-rules."""
        raise_for_result(await self._engine.async_set_auto(False, self._context), "auto")


class HomeModeOverlaySwitch(HomeModesEntity, SwitchEntity):
    """Toggles an overlay role."""

    _attr_translation_key = "overlay"

    def __init__(self, coordinator: HomeModesCoordinator, engine: ChangeEngine, role: Role) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, f"{KEY_ROLE_OVERLAY_SWITCH}{role.id}")
        self._engine = engine
        self._role = role
        self._object_id = f"{KEY_ROLE_OVERLAY_SWITCH}{role.id}"
        self._attr_translation_placeholders = {"role_name": role.name}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the stable role id."""
        return {"mode_id": self._role.id, "role": self._role.type.value}

    @property
    def is_on(self) -> bool:
        """Return True if the overlay is active."""
        return self._role.id in self.coordinator.data.overlays

    async def _async_set(self, active: bool) -> None:
        result = await self._engine.async_set_overlay(
            self._role.id, active, ChangeSource.MANUAL, context=self._context
        )
        raise_for_result(result, self._role.name)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate the overlay."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate the overlay."""
        await self._async_set(False)
