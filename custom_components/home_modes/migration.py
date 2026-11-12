"""Migration helper: map the options of an old input_select to Home Modes roles.

Everything here is read-only until the caller applies a plan to the config entry
options. Nothing in this module edits or deletes automations, scripts, helpers or YAML.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from homeassistant.components import automation, script
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CUSTOM_PREFIX,
    DOMAIN,
    KEY_ROLE_BINARY_SENSOR,
    MAX_CUSTOM_MODES,
    ROLE_AWAY,
    ROLE_DND,
    ROLE_GUEST,
    ROLE_HOME,
    ROLE_NIGHT,
    ROLE_VACATION,
)
from .models import Role, RoleKind, RoleType, validate_roles

TARGET_CUSTOM = "custom"
TARGET_SKIP = "skip"
MAX_REPORT_ITEMS = 25

# Word lists for the name matching, checked in this order (first match wins).
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ROLE_DND, ("dnd", "do not disturb", "donotdisturb", "quiet")),
    (ROLE_GUEST, ("guest", "guests", "visitor", "visitors")),
    (ROLE_VACATION, ("vacation", "holiday", "holidays")),
    (ROLE_AWAY, ("away", "out", "outside", "leaving")),
    (ROLE_NIGHT, ("night", "sleep", "sleeping", "bed", "bedtime")),
    (ROLE_HOME, ("home", "house", "present", "in")),
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _keyword_role(option: str) -> str | None:
    text = " ".join(_words(option))
    words = set(text.split())
    for role_id, keywords in _KEYWORDS:
        for keyword in keywords:
            if (" " in keyword and keyword in text) or keyword in words:
                return role_id
    return None


def suggest_mapping(options: list[str], roles: list[Role]) -> dict[str, str]:
    """Suggest a target (role id, "custom" or "skip") for every option.

    1. An existing role with exactly the same name (case-insensitive) wins.
    2. Otherwise name matching decides (home, night/sleep/bed, away/out,
       vacation/holiday, guest, dnd/do not disturb/quiet).
    3. Anything else becomes a custom mode, up to the cap; further ones are skipped.
    A role is suggested at most once; a second match becomes custom.
    """
    by_name = {r.name.strip().casefold(): r.id for r in roles if r.kind is not RoleKind.DERIVED}
    settable = {r.id for r in roles if r.kind is not RoleKind.DERIVED}
    taken: set[str] = set()
    result: dict[str, str] = {}
    customs = sum(1 for r in roles if r.type is RoleType.CUSTOM)
    for option in options:
        target = by_name.get(option.strip().casefold())
        if target is None:
            guess = _keyword_role(option)
            target = guess if guess in settable else None
        if target is not None and target not in taken:
            taken.add(target)
            result[option] = target
        elif customs < MAX_CUSTOM_MODES:
            customs += 1
            result[option] = TARGET_CUSTOM
        else:
            result[option] = TARGET_SKIP
    return result


@dataclass
class Plan:
    """The result of validating a mapping: a preview, and the roles to write."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    mirror_mapping: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """Return whether the plan can be applied."""
        return not self.errors


def build_plan(roles: list[Role], options: list[str], mapping: Mapping[str, str]) -> Plan:
    """Validate a mapping and compute the new role list (nothing is written)."""
    plan = Plan(roles=list(roles))
    by_id = {r.id: r for r in roles}
    used_custom = {r.id for r in roles if r.type is RoleType.CUSTOM}
    seen: dict[str, str] = {}
    for option in options:
        name = option.strip()
        target = mapping.get(option)
        if target is None:
            plan.errors.append(f"missing_mapping:{option}")
            continue
        if target == TARGET_SKIP:
            plan.rows.append({"option": option, "action": "skip", "role": None})
            continue
        if target == TARGET_CUSTOM:
            free = next(
                (
                    f"{CUSTOM_PREFIX}{n}"
                    for n in range(1, MAX_CUSTOM_MODES + 1)
                    if f"{CUSTOM_PREFIX}{n}" not in used_custom
                ),
                None,
            )
            if free is None:
                plan.errors.append("max_custom_modes")
                continue
            used_custom.add(free)
            plan.roles.append(Role(free, name))
            plan.mirror_mapping[free] = option
            plan.rows.append(
                {"option": option, "action": "create", "role": free, "name_before": None}
            )
            continue
        role = by_id.get(target)
        if role is None or role.kind is RoleKind.DERIVED:
            plan.errors.append(f"unknown_target:{option}")
            continue
        if target in seen:
            plan.errors.append(f"duplicate_role:{target}")
            continue
        seen[target] = option
        changes = []
        if role.name != name:
            changes.append("rename")
        if not role.enabled:
            changes.append("enable")
        plan.roles = [
            replace(r, name=name, enabled=True) if r.id == target else r for r in plan.roles
        ]
        plan.mirror_mapping[target] = option
        plan.rows.append(
            {
                "option": option,
                "action": "+".join(changes) or "keep",
                "role": target,
                "name_before": role.name,
            }
        )
    if not plan.errors and (error := validate_roles(plan.roles)) is not None:
        plan.errors.append(error)
    return plan


def _binary_sensor_id(hass: HomeAssistant, entry_id: str, role_id: str) -> tuple[str, bool]:
    """Return (entity id, exists). New roles get the predicted id until they exist."""
    registry = er.async_get(hass)
    found = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry_id}_{KEY_ROLE_BINARY_SENSOR}{role_id}"
    )
    if found:
        return found, True
    return f"binary_sensor.home_mode_{role_id}", False


def replacement_snippets(
    hass: HomeAssistant, entry_id: str, input_select: str, plan: Plan
) -> list[dict[str, Any]]:
    """Return copy-paste replacements per mapped option (suggestions, never applied)."""
    snippets = []
    for row in plan.rows:
        if not row.get("role"):
            continue
        sensor, exists = _binary_sensor_id(hass, entry_id, row["role"])
        snippets.append(
            {
                "option": row["option"],
                "role": row["role"],
                "entity_id": sensor,
                "entity_exists_yet": exists,
                "condition": (
                    f'condition: state\nentity_id: {sensor}\nstate: "on"\n'
                    f'# was: entity_id: {input_select}, state: "{row["option"]}"'
                ),
                "trigger": (
                    f'trigger: state\nentity_id: {sensor}\nto: "on"\n'
                    f'# was: entity_id: {input_select}, to: "{row["option"]}"'
                ),
                "template": (
                    f"{{{{ is_state('{sensor}', 'on') }}}}"
                    f"  # was is_state('{input_select}', '{row['option']}')"
                ),
            }
        )
    return snippets


def _mentions(blob: str, options: list[str]) -> list[str]:
    low = blob.casefold()
    return [o for o in options if o.casefold() in low]


def usage_report(
    hass: HomeAssistant, input_select: str, options: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """List automations, scripts and UI template helpers that reference the input_select.

    Read-only. Automations and scripts come from Home Assistant's own loaded
    configuration (entity references plus a text search of the raw config, which also
    finds templates). Template helpers created in the UI are searched through their
    config entry options. Template sensors written in YAML cannot be inspected.
    """
    report: dict[str, list[dict[str, Any]]] = {"automations": [], "scripts": [], "templates": []}

    def blob(config: Any) -> str:
        try:
            return json.dumps(config, default=str)
        except TypeError, ValueError:
            return ""

    component = hass.data.get(automation.DATA_COMPONENT)
    if component:
        for entity in component.entities:
            raw = blob(getattr(entity, "raw_config", None))
            if input_select in entity.referenced_entities or input_select in raw:
                report["automations"].append(
                    {
                        "entity_id": entity.entity_id,
                        "name": entity.name,
                        "mentions": _mentions(raw, options),
                    }
                )
    scripts = hass.data.get(script.DOMAIN)
    if scripts is not None:
        for entity in scripts.entities:
            raw = blob(getattr(entity, "raw_config", None))
            if input_select in entity.referenced_entities or input_select in raw:
                report["scripts"].append(
                    {
                        "entity_id": entity.entity_id,
                        "name": entity.name,
                        "mentions": _mentions(raw, options),
                    }
                )
    for config_entry in hass.config_entries.async_entries("template"):
        raw = blob(dict(config_entry.options))
        if input_select in raw:
            report["templates"].append(
                {"entry_id": config_entry.entry_id, "name": config_entry.title}
            )
    for key in report:
        report[key] = sorted(report[key], key=lambda i: str(i.get("entity_id", i.get("name"))))[
            :MAX_REPORT_ITEMS
        ]
    return report


def input_select_options(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """Return the options of an input_select, or None if it does not exist."""
    if not entity_id.startswith("input_select."):
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    options = state.attributes.get("options")
    return [str(o) for o in options] if isinstance(options, list) else []


def apply_plan_options(
    options: Mapping[str, Any],
    plan: Plan,
    entity_id: str,
    mirror: bool,
    mirror_overlays: bool | None = None,
) -> dict[str, Any]:
    """Return new config entry options with the plan applied (does not write them).

    ``mirror_overlays=None`` keeps the stored "Mirror overlays" value (default off).
    """
    from .const import CONF_MIRROR, CONF_ROLES

    if mirror_overlays is None:
        previous = options.get(CONF_MIRROR) or {}
        mirror_overlays = bool(previous.get("overlays", False))
    return {
        **options,
        CONF_ROLES: [r.to_dict() for r in plan.roles],
        CONF_MIRROR: {
            "enabled": mirror,
            "entity_id": entity_id,
            "mapping": dict(plan.mirror_mapping),
            "overlays": mirror_overlays,
        },
    }


def describe_plan(plan: Plan) -> str:
    """Return a short markdown preview of a plan (used by the options flow)."""
    lines = []
    for row in plan.rows:
        option = row["option"]
        action = row["action"]
        if action == "skip":
            lines.append(f"- **{option}**: skipped")
        elif action == "create":
            lines.append(f"- **{option}**: new custom mode")
        else:
            before = row.get("name_before")
            lines.append(f"- **{option}**: {row['role']} ({action}, was {before})")
    return "\n".join(lines)


async def async_run_import(
    hass: HomeAssistant,
    entry: Any,
    *,
    entity_id: str,
    mapping: Mapping[str, str] | None,
    confirm: bool,
    mirror: bool,
    mirror_overlays: bool | None = None,
) -> dict[str, Any]:
    """Dry-run or apply the import. Without confirm nothing is written."""
    from homeassistant.exceptions import ServiceValidationError

    options = input_select_options(hass, entity_id)
    if options is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="input_select_not_found",
            translation_placeholders={"entity_id": entity_id},
        )
    coordinator = entry.runtime_data.coordinator
    roles = list(coordinator.roles)
    unknown = sorted(set(mapping or {}) - set(options))
    suggestions = suggest_mapping(options, roles)
    chosen = {**suggestions, **(mapping or {})}
    plan = build_plan(roles, options, chosen)
    problems = [f"unknown_option:{o}" for o in unknown] + plan.errors
    applied = False
    if confirm:
        if problems:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="import_invalid",
                translation_placeholders={"problems": ", ".join(problems)},
            )
        hass.config_entries.async_update_entry(
            entry,
            options=apply_plan_options(entry.options, plan, entity_id, mirror, mirror_overlays),
        )
        hass.config_entries.async_schedule_reload(entry.entry_id)
        applied = True
    return {
        "input_select": entity_id,
        "applied": applied,
        "valid": not problems,
        "problems": problems,
        "mirror": mirror,
        "mirror_overlays": bool(
            mirror_overlays
            if mirror_overlays is not None
            else (entry.options.get("mirror") or {}).get("overlays", False)
        ),
        "suggestions": suggestions,
        "preview": plan.rows,
        "snippets": replacement_snippets(hass, entry.entry_id, entity_id, plan),
        "usage": usage_report(hass, entity_id, options),
    }
