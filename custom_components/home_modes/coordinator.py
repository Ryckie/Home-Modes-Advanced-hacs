"""Coordinator and base entity for Home Modes Advanced."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ROLES,
    CONF_USER_RULES,
    DEVICE_NAME,
    DOMAIN,
    KEY_AUTO,
    KEY_PREVIOUS,
    KEY_ROLE_BINARY_SENSOR,
    KEY_ROLE_OVERLAY_SWITCH,
    KEY_SELECT,
    KEY_SINCE,
    KEY_TRIGGER_REASON,
    ROLE_HOME,
    STORAGE_MINOR_VERSION,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)
from .models import (
    ChangeSource,
    HomeModesState,
    PresenceProvider,
    Role,
    RoleKind,
    TriggerInfo,
    UnknownPresenceProvider,
)
from .permissions import UserRule, parse_user_rules
from .settings import (
    AutoSettings,
    IntegrationSettings,
    parse_integration_settings,
    parse_settings,
)

_LOGGER = logging.getLogger(__name__)


class HomeModesCoordinator(DataUpdateCoordinator[HomeModesState]):
    """Holds the configured roles and the restored runtime state.

    State is pushed (via the change engine), never polled.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}",
            minor_version=STORAGE_MINOR_VERSION,
        )
        self.presence: PresenceProvider = UnknownPresenceProvider()
        self.roles: tuple[Role, ...] = self._parse_roles(entry)
        self.user_rules: dict[str, UserRule] = parse_user_rules(entry.options.get(CONF_USER_RULES))
        self.settings: AutoSettings = parse_settings(entry.options)
        self.integrations: IntegrationSettings = parse_integration_settings(entry.options)

    @staticmethod
    def _parse_roles(entry: ConfigEntry) -> tuple[Role, ...]:
        roles: list[Role] = []
        for raw in entry.options.get(CONF_ROLES, []):
            try:
                roles.append(Role.from_dict(raw))
            except KeyError, TypeError, ValueError:
                _LOGGER.warning(
                    "Ignoring invalid role definition (id: %s)",
                    raw.get("id") if isinstance(raw, dict) else None,
                )
        return tuple(roles)

    async def _async_update_data(self) -> HomeModesState:
        """Return the current state (state is pushed, never polled)."""
        return self.data

    # --- role helpers -------------------------------------------------------

    def role(self, role_id: str) -> Role | None:
        """Return a role by id."""
        return next((r for r in self.roles if r.id == role_id), None)

    def find_role(self, value: str) -> Role | None:
        """Find a role by id or (case-insensitive) name."""
        needle = value.strip().casefold()
        for role in self.roles:
            if role.id.casefold() == needle:
                return role
        for role in self.roles:
            if role.name.strip().casefold() == needle:
                return role
        return None

    @property
    def enabled_roles(self) -> list[Role]:
        """Return enabled roles in configured order."""
        return [r for r in self.roles if r.enabled]

    @property
    def selectable_primaries(self) -> list[Role]:
        """Return enabled roles that can be the primary mode."""
        return [r for r in self.enabled_roles if r.selectable_primary]

    @property
    def overlay_roles(self) -> list[Role]:
        """Return enabled overlay roles."""
        return [r for r in self.enabled_roles if r.kind is RoleKind.OVERLAY]

    def first_enabled_primary(self) -> Role | None:
        """Return the first enabled role of kind primary."""
        return next((r for r in self.enabled_roles if r.kind is RoleKind.PRIMARY), None)

    def initial_primary(self) -> Role:
        """Return the primary used on first setup: home, else first enabled."""
        home = self.role(ROLE_HOME)
        if home is not None and home.enabled:
            return home
        first = self.first_enabled_primary()
        if first is None:
            raise ConfigEntryError(translation_domain=DOMAIN, translation_key="no_primary_enabled")
        return first

    def expected_unique_ids(self) -> set[str]:
        """Return the unique ids of all entities that should exist."""
        prefix = self.config_entry.entry_id
        ids = {
            f"{prefix}_{KEY_SELECT}",
            f"{prefix}_{KEY_SINCE}",
            f"{prefix}_{KEY_PREVIOUS}",
            f"{prefix}_{KEY_TRIGGER_REASON}",
            f"{prefix}_{KEY_AUTO}",
        }
        for role in self.enabled_roles:
            ids.add(f"{prefix}_{KEY_ROLE_BINARY_SENSOR}{role.id}")
            if role.kind is RoleKind.OVERLAY:
                ids.add(f"{prefix}_{KEY_ROLE_OVERLAY_SWITCH}{role.id}")
        return ids

    # --- state --------------------------------------------------------------

    async def async_restore(self) -> None:
        """Load stored state, or create the initial state on first setup."""
        stored = await self._store.async_load()
        state: HomeModesState | None = None
        if stored is not None:
            try:
                state = HomeModesState.from_dict(stored)
            except KeyError, TypeError, ValueError:
                _LOGGER.warning("Stored state is corrupt, starting fresh")
        if state is None:
            state = HomeModesState(
                primary=self.initial_primary().id,
                since=dt_util.utcnow(),
                last_trigger=TriggerInfo(ChangeSource.SYSTEM, "initial"),
            )
            self._store.async_delay_save(state.to_dict, STORAGE_SAVE_DELAY)
        self.async_set_updated_data(state)

    def async_apply_state(self, state: HomeModesState) -> None:
        """Publish a new state to entities and schedule saving it."""
        self.async_set_updated_data(state)
        self._store.async_delay_save(state.to_dict, STORAGE_SAVE_DELAY)

    def async_set_auto_enabled(self, enabled: bool) -> None:
        """Store the auto-rules flag."""
        self.async_apply_state(replace(self.data, auto_enabled=enabled))

    async def async_flush(self) -> None:
        """Write the current state to storage immediately."""
        await self._store.async_save(self.data.to_dict())


class HomeModesEntity(CoordinatorEntity[HomeModesCoordinator]):
    """Base class for all Home Modes entities."""

    _attr_has_entity_name = True
    _object_id: str | None = None

    def __init__(self, coordinator: HomeModesCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def suggested_object_id(self) -> str | None:
        """Return a stable object id (the role id) for per-role entities."""
        if self._object_id is not None:
            return self._object_id
        return super().suggested_object_id
