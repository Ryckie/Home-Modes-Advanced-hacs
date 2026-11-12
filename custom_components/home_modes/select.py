"""Select platform: the house mode selector."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, KEY_SELECT
from .coordinator import HomeModesCoordinator, HomeModesEntity
from .engine import ChangeEngine, HomeModesConfigEntry, raise_for_result
from .models import ChangeSource, role_type_from_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeModesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entity."""
    runtime = entry.runtime_data
    async_add_entities([HomeModeSelect(runtime.coordinator, runtime.engine)])


class HomeModeSelect(HomeModesEntity, SelectEntity):
    """Select entity for the primary mode. Options are the role names."""

    _attr_name = None  # main entity of the device -> select.home_mode

    def __init__(self, coordinator: HomeModesCoordinator, engine: ChangeEngine) -> None:
        """Initialize the select."""
        super().__init__(coordinator, KEY_SELECT)
        self._engine = engine

    @property
    def options(self) -> list[str]:
        """Return the names of all enabled selectable primaries."""
        return [role.name for role in self.coordinator.selectable_primaries]

    @property
    def current_option(self) -> str | None:
        """Return the name of the active primary."""
        role = self.coordinator.role(self.coordinator.data.primary)
        return role.name if role is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the stable role id, overlays and the data the dashboard cards read."""
        data = self.coordinator.data
        override = data.override
        temporary = data.temporary
        revert = self.coordinator.role(temporary.revert_to) if temporary else None
        return {
            "role": role_type_from_id(data.primary).value,
            "mode_id": data.primary,
            "overlays": list(data.overlays),
            "since": data.since.isoformat(),
            "auto": data.auto_enabled,
            "override": (
                {
                    "mode": override.mode.value,
                    "until": override.until.isoformat() if override.until else None,
                }
                if override
                else None
            ),
            "temporary": (
                {
                    "until": temporary.until.isoformat(),
                    "revert_to": temporary.revert_to,
                    "revert_to_name": revert.name if revert else None,
                }
                if temporary
                else None
            ),
        }

    async def async_select_option(self, option: str) -> None:
        """Select a primary mode (the calling user's context is in self._context)."""
        role = self.coordinator.find_role(option)
        if role is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_role",
                translation_placeholders={"role": option},
            )
        result = await self._engine.async_set_primary(
            role.id, ChangeSource.MANUAL, context=self._context
        )
        raise_for_result(result, role.name)
