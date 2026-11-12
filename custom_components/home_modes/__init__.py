"""Home Modes Advanced: a first-class house mode signal for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import probatio as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryError,
    ServiceValidationError,
    UnsupportedStorageVersionError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .actions import ActionRunner
from .alarmo import AlarmoBridge
from .assist import async_register_intents
from .autorules import AutoRules
from .const import (
    ATTR_ACTIVE,
    ATTR_DURATION,
    ATTR_MODE,
    ATTR_OVERLAY,
    ATTR_OVERRIDE_FLAG,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_HISTORY,
    SERVICE_IMPORT_INPUT_SELECT,
    SERVICE_REVERT,
    SERVICE_SET_AUTO,
    SERVICE_SET_MODE,
    SERVICE_SET_OVERLAY,
    SERVICE_SET_TEMPORARY,
    STORAGE_MINOR_VERSION,
    STORAGE_VERSION,
)
from .coordinator import HomeModesCoordinator
from .engine import (
    ChangeEngine,
    HomeModesConfigEntry,
    HomeModesRuntime,
    raise_for_result,
)
from .frontend import async_register_frontend
from .history import HistoryLog
from .migration import async_run_import
from .mirror import InputSelectMirror
from .models import ChangeRequest, ChangeSource, RoleKind
from .notify import Notifier
from .presence import PresenceTracker
from .vacation import VacationSimulator
from .ws import async_register_websocket

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _non_zero_duration(value: timedelta) -> timedelta:
    """Require a duration longer than zero."""
    if value <= timedelta(0):
        raise vol.Invalid("duration must be longer than zero")
    return value


SET_MODE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_MODE): cv.string, vol.Optional(ATTR_OVERRIDE_FLAG): cv.boolean}
)
SET_TEMPORARY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MODE): cv.string,
        vol.Required(ATTR_DURATION): vol.All(cv.time_period, _non_zero_duration),
    }
)
EMPTY_SCHEMA = vol.Schema({})
IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("mapping"): {cv.string: cv.string},
        vol.Optional("confirm", default=False): cv.boolean,
        vol.Optional("mirror", default=False): cv.boolean,
        vol.Optional("mirror_overlays"): cv.boolean,
    }
)
SET_OVERLAY_SCHEMA = vol.Schema(
    {vol.Required(ATTR_OVERLAY): cv.string, vol.Required(ATTR_ACTIVE): cv.boolean}
)


def _get_runtime(hass: HomeAssistant) -> HomeModesRuntime:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0].runtime_data


def _resolve(runtime: HomeModesRuntime, value: str, kind: RoleKind) -> tuple[str, str]:
    """Resolve a role id or name, checking its kind. Returns (id, name)."""
    role = runtime.coordinator.find_role(value)
    if role is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_role",
            translation_placeholders={"role": value},
        )
    is_overlay = role.kind is RoleKind.OVERLAY
    if is_overlay != (kind is RoleKind.OVERLAY):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="wrong_kind",
            translation_placeholders={"role": role.name},
        )
    return role.id, role.name


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration services."""

    async def _set_mode(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        role_id, name = _resolve(runtime, call.data[ATTR_MODE], RoleKind.PRIMARY)
        result = await runtime.engine.async_change(
            ChangeRequest(
                role_id,
                ChangeSource.MANUAL,
                context=call.context,
                override=call.data.get(ATTR_OVERRIDE_FLAG),
            )
        )
        raise_for_result(result, name)

    async def _set_temporary(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        role_id, name = _resolve(runtime, call.data[ATTR_MODE], RoleKind.PRIMARY)
        duration: timedelta = call.data[ATTR_DURATION]
        result = await runtime.engine.async_set_temporary(role_id, duration, call.context)
        raise_for_result(result, name)

    async def _revert(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        result = await runtime.engine.async_revert(call.context)
        raise_for_result(result, "previous")

    async def _set_auto(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        result = await runtime.engine.async_set_auto_mode(call.context)
        raise_for_result(result, "auto")

    async def _set_overlay(call: ServiceCall) -> None:
        runtime = _get_runtime(hass)
        role_id, name = _resolve(runtime, call.data[ATTR_OVERLAY], RoleKind.OVERLAY)
        result = await runtime.engine.async_set_overlay(
            role_id, call.data[ATTR_ACTIVE], ChangeSource.MANUAL, context=call.context
        )
        raise_for_result(result, name)

    async def _clear_history(call: ServiceCall) -> None:
        await _get_runtime(hass).history.async_clear()

    async def _import_input_select(call: ServiceCall) -> dict[str, Any]:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
        return await async_run_import(
            hass,
            entries[0],
            entity_id=call.data["entity_id"],
            mapping=call.data.get("mapping"),
            confirm=call.data["confirm"],
            mirror=call.data["mirror"],
            mirror_overlays=call.data.get("mirror_overlays"),
        )

    async_register_admin_service(hass, DOMAIN, SERVICE_CLEAR_HISTORY, _clear_history, EMPTY_SCHEMA)
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_IMPORT_INPUT_SELECT,
        _import_input_select,
        IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_intents(hass)
    await async_register_frontend(hass)
    async_register_websocket(hass)
    hass.services.async_register(DOMAIN, SERVICE_SET_MODE, _set_mode, SET_MODE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_OVERLAY, _set_overlay, SET_OVERLAY_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_TEMPORARY, _set_temporary, SET_TEMPORARY_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REVERT, _revert, EMPTY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_AUTO, _set_auto, EMPTY_SCHEMA)
    return True


STORE_SUFFIXES = ("", ".history", ".vacation")


def _store(hass: HomeAssistant, entry: HomeModesConfigEntry, suffix: str) -> Store[dict[str, Any]]:
    return Store(
        hass,
        STORAGE_VERSION,
        f"{DOMAIN}.{entry.entry_id}{suffix}",
        minor_version=STORAGE_MINOR_VERSION,
    )


async def _async_check_storage(hass: HomeAssistant, entry: HomeModesConfigEntry) -> None:
    """Refuse to start on files written by a newer major version (a downgrade).

    The files are not touched, so installing the newer version again finds them intact.
    """
    for suffix in STORE_SUFFIXES:
        try:
            await _store(hass, entry, suffix).async_load()
        except UnsupportedStorageVersionError as err:
            raise ConfigEntryError(
                translation_domain=DOMAIN, translation_key="storage_too_new"
            ) from err


async def async_setup_entry(hass: HomeAssistant, entry: HomeModesConfigEntry) -> bool:
    """Set up Home Modes Advanced from a config entry."""
    await _async_check_storage(hass, entry)
    coordinator = HomeModesCoordinator(hass, entry)
    await coordinator.async_restore()
    engine = ChangeEngine(hass, coordinator)
    # Pipeline hooks (exit actions -> state -> enter actions -> event -> history,
    # notify, Alarmo) are registered before the first change can happen.
    history = HistoryLog(hass, coordinator, engine)
    await history.async_setup()
    notifier = Notifier(hass, coordinator, engine, history)
    notifier.async_setup()
    runner = ActionRunner(hass, coordinator, engine)
    unsubs = runner.async_register()
    bridge = AlarmoBridge(hass, coordinator, engine, history, notifier)
    bridge.async_setup()
    mirror = InputSelectMirror(hass, coordinator, engine, history)
    mirror.async_setup()
    vacation = VacationSimulator(hass, coordinator, history)
    await engine.async_reconcile()
    tracker = PresenceTracker(hass, coordinator.settings.persons)
    coordinator.presence = tracker
    rules = AutoRules(hass, entry, coordinator, engine, tracker)
    entry.runtime_data = HomeModesRuntime(
        coordinator, engine, rules, history, notifier, bridge, mirror, vacation, runner, unsubs
    )

    # Remove entities of roles that are no longer enabled or no longer exist.
    registry = er.async_get(hass)
    expected = coordinator.expected_unique_ids()
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.unique_id not in expected:
            registry.async_remove(registry_entry.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    rules.async_setup()
    await vacation.async_setup()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeModesConfigEntry) -> bool:
    """Unload a config entry."""
    runtime = entry.runtime_data
    runtime.rules.async_stop()
    await runtime.vacation.async_unload()
    runtime.bridge.async_unload()
    runtime.mirror.async_unload()
    runtime.notifier.async_unload()
    for unsub in runtime.unsubs:
        unsub()
    runtime.engine.async_stop()
    await runtime.history.async_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await runtime.coordinator.async_flush()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: HomeModesConfigEntry) -> None:
    """Delete stored state when the entry is removed."""
    for suffix in STORE_SUFFIXES:
        await _store(hass, entry, suffix).async_remove()
