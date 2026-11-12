"""Diagnostics for Home Modes Advanced (everything that identifies a person is redacted)."""

from __future__ import annotations

import sys
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DEFAULT_ROLE_NAMES, DOMAIN
from .engine import HomeModesConfigEntry
from .models import Role

REDACTED = "**REDACTED**"
HISTORY_LIMIT = 50
# History bridge notes keep only these keys; the rest (targets, entity ids) is dropped.
_NOTE_KEYS = ("reason", "event", "role", "state", "result")

# Safety net applied to the finished report: any key with one of these names is
# redacted, even if a future change adds it by mistake.
TO_REDACT = {
    "user_id",
    "user",
    "set_by_user",
    "targets",
    "services",
    "message",
    "title",
    "entity_id",
    "lights",
    "persons",
    "name_custom",
}


def _role_summary(role: Role) -> dict[str, Any]:
    """Return a role without its actions; names are only kept when they are defaults."""
    default = DEFAULT_ROLE_NAMES.get(role.id)
    return {
        "id": role.id,
        "type": role.type.value,
        "kind": role.kind.value,
        "enabled": role.enabled,
        "name": role.name if role.name == default else REDACTED,
        "enter_actions": len(role.enter_actions),
        "exit_actions": len(role.exit_actions),
    }


def _history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries[-HISTORY_LIMIT:]:
        notes = [
            {k: n[k] for k in _NOTE_KEYS if k in n}
            for n in entry.get("bridge") or []
            if isinstance(n, dict)
        ]
        out.append(
            {
                "ts": entry.get("ts"),
                "kind": entry.get("kind"),
                "from": entry.get("from"),
                "to": entry.get("to"),
                "role": entry.get("role"),
                "source": entry.get("source"),
                "rule": entry.get("rule"),
                "had_user": bool(entry.get("user_id")),
                "action_failures": len(entry.get("action_failures") or []),
                "bridge": notes,
            }
        )
    return out


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeModesConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    state = coordinator.data
    settings = coordinator.settings
    integ = coordinator.integrations
    integration = await async_get_integration(hass, DOMAIN)

    override = state.override
    data: dict[str, Any] = {
        "versions": {
            "integration": str(integration.version),
            "home_assistant": HA_VERSION,
            "python": ".".join(str(p) for p in sys.version_info[:3]),
        },
        "state": {
            "primary": state.primary,
            "previous": state.previous,
            "since": state.since.isoformat(),
            "overlays": list(state.overlays),
            "auto_enabled": state.auto_enabled,
            "last_trigger": state.last_trigger.to_dict() if state.last_trigger else None,
            "override": (
                {
                    "mode": override.mode.value,
                    "source": override.set_by,
                    "until": override.until.isoformat() if override.until else None,
                }
                if override
                else None
            ),
            "temporary": state.temporary.to_dict() if state.temporary else None,
            "all_away_since": state.all_away_since.isoformat() if state.all_away_since else None,
        },
        "timers": runtime.rules.timer_summary(),
        "roles": [_role_summary(r) for r in coordinator.roles],
        "settings": {
            "away_delay_min": settings.away_delay.total_seconds() / 60,
            "vacation_after_h": settings.vacation_after.total_seconds() / 3600,
            "persons_configured": len(settings.persons),
            "night_methods": sorted(settings.night.methods),
            "morning_methods": sorted(settings.morning.methods),
            "night_sensors": len(settings.night.sleep_sensors)
            + len(settings.night.charging_sensors),
            "morning_sensors": len(settings.morning.motion_sensors)
            + len(settings.morning.alarm_sensors),
            "override": {
                "until": settings.override.until,
                "duration_min": settings.override.duration.total_seconds() / 60,
            },
            "user_rules": {
                "count": len(coordinator.user_rules),
                "allow_list": sum(
                    1 for r in coordinator.user_rules.values() if r.mode.value == "allow_list"
                ),
            },
            "actions_timeout_s": integ.actions_timeout,
            "history_max": integ.history_max,
            "alarmo": {
                "enabled": integ.alarmo.enabled,
                "direction": integ.alarmo.direction,
                "apply_auto": integ.alarmo.apply_auto,
                "entity_configured": bool(integ.alarmo.entity_id),
                "mappings": [
                    {
                        "state": m.state,
                        "role": m.role,
                        "to_alarmo": m.to_alarmo,
                        "from_alarmo": m.from_alarmo,
                        "allow_disarm": m.allow_disarm,
                    }
                    for m in integ.alarmo.mappings
                ],
            },
            "vacation": {
                "enabled": integ.vacation.enabled,
                "strategy": integ.vacation.strategy,
                "roles": list(integ.vacation.roles),
                "lights_configured": len(integ.vacation.lights),
                "running": runtime.vacation.active,
            },
            "notify": {
                "rate_limit_s": integ.notify.rate_limit.total_seconds(),
                "rules": [
                    {
                        "event": r.event,
                        "role": r.role,
                        "target_count": len(r.targets) + len(r.services),
                        "has_message": bool(r.message),
                    }
                    for r in integ.notify.rules
                ],
            },
            "mirror": {
                "enabled": integ.mirror.enabled,
                "entity_configured": bool(integ.mirror.entity_id),
                "mapped_roles": sorted(integ.mirror.mapping),
            },
        },
        "history": _history(runtime.history.entries),
    }
    return async_redact_data(data, TO_REDACT)
