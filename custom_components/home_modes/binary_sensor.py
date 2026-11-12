"""Binary sensor platform: one sensor per enabled role."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEY_ROLE_BINARY_SENSOR, ROLE_ALL_HOME
from .coordinator import HomeModesCoordinator, HomeModesEntity
from .engine import HomeModesConfigEntry
from .models import Role, RoleKind


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeModesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one binary sensor per enabled role."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        HomeModeRoleBinarySensor(coordinator, role) for role in coordinator.enabled_roles
    )


class HomeModeRoleBinarySensor(HomeModesEntity, BinarySensorEntity):
    """On when the role is active (primary/overlay) or true (derived)."""

    _attr_translation_key = "role"

    def __init__(self, coordinator: HomeModesCoordinator, role: Role) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, f"{KEY_ROLE_BINARY_SENSOR}{role.id}")
        self._role = role
        self._object_id = role.id
        self._attr_translation_placeholders = {"role_name": role.name}

    async def async_added_to_hass(self) -> None:
        """Follow presence changes for derived roles."""
        await super().async_added_to_hass()
        if self._role.kind is RoleKind.DERIVED:
            self.async_on_remove(
                self.coordinator.presence.async_add_listener(self.async_write_ha_state)
            )

    @property
    def is_on(self) -> bool | None:
        """Return the role state."""
        state = self.coordinator.data
        if self._role.kind is RoleKind.OVERLAY:
            return self._role.id in state.overlays
        if self._role.kind is RoleKind.DERIVED:
            presence = self.coordinator.presence
            return presence.all_home if self._role.id == ROLE_ALL_HOME else presence.all_away
        return state.primary == self._role.id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the role type, the mode id and, for derived roles, selected."""
        attrs: dict[str, Any] = {"role": self._role.type.value, "mode_id": self._role.id}
        if self._role.kind is RoleKind.DERIVED:
            attrs["selected"] = self.coordinator.data.primary == self._role.id
        return attrs
