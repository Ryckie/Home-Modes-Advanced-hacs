"""Sensor platform: since, previous and trigger reason."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEY_PREVIOUS, KEY_SINCE, KEY_TRIGGER_REASON
from .coordinator import HomeModesCoordinator, HomeModesEntity
from .engine import HomeModesConfigEntry
from .models import ChangeSource


@dataclass(frozen=True, kw_only=True)
class HomeModesSensorDescription(SensorEntityDescription):
    """Sensor description with a value function."""

    value_fn: Callable[[HomeModesCoordinator], datetime | str | None]
    attrs_fn: Callable[[HomeModesCoordinator], dict[str, Any]] | None = None


def _previous_name(coordinator: HomeModesCoordinator) -> str | None:
    previous = coordinator.data.previous
    if previous is None:
        return None
    role = coordinator.role(previous)
    return role.name if role is not None else previous


SENSORS: tuple[HomeModesSensorDescription, ...] = (
    HomeModesSensorDescription(
        key=KEY_SINCE,
        translation_key=KEY_SINCE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.data.since,
    ),
    HomeModesSensorDescription(
        key=KEY_PREVIOUS,
        translation_key=KEY_PREVIOUS,
        value_fn=_previous_name,
        attrs_fn=lambda c: {"role": c.data.previous},
    ),
    HomeModesSensorDescription(
        key=KEY_TRIGGER_REASON,
        translation_key=KEY_TRIGGER_REASON,
        device_class=SensorDeviceClass.ENUM,
        options=[source.value for source in ChangeSource],
        value_fn=lambda c: c.data.last_trigger.source if c.data.last_trigger else None,
        attrs_fn=lambda c: {"rule": c.data.last_trigger.rule if c.data.last_trigger else None},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeModesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(HomeModesSensor(coordinator, desc) for desc in SENSORS)


class HomeModesSensor(HomeModesEntity, SensorEntity):
    """A sensor describing the primary mode."""

    entity_description: HomeModesSensorDescription

    def __init__(
        self, coordinator: HomeModesCoordinator, description: HomeModesSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> datetime | str | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator) if fn else None
