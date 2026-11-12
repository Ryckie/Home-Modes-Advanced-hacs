"""Config flow and options flow for Home Modes Advanced."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    ActionSelector,
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)
from homeassistant.helpers.template import Template

from .const import (
    CONF_ACTIONS_TIMEOUT,
    CONF_ALARMO,
    CONF_AWAY_DELAY_MIN,
    CONF_HISTORY,
    CONF_MORNING,
    CONF_NIGHT,
    CONF_NOTIFY,
    CONF_OVERRIDE,
    CONF_PERSONS,
    CONF_PRESET,
    CONF_ROLES,
    CONF_USER_RULES,
    CONF_VACATION_AFTER_H,
    CONF_VACATION_SIM,
    CUSTOM_PREFIX,
    DEFAULT_ROLE_NAMES,
    DEFAULT_ROLE_ORDER,
    DOMAIN,
    MAX_CUSTOM_MODES,
    MORNING_ALARM,
    MORNING_METHODS,
    MORNING_MOTION,
    NIGHT_METHODS,
    NIGHT_PHONE_CHARGING,
    NIGHT_SLEEP_SENSORS,
    PRESET_ENABLED_ROLES,
    PRESET_SIMPLE,
    PRESETS,
    TITLE,
    UNTIL_MODES,
)
from .migration import (
    TARGET_CUSTOM,
    TARGET_SKIP,
    apply_plan_options,
    build_plan,
    describe_plan,
    input_select_options,
    replacement_snippets,
    suggest_mapping,
    usage_report,
)
from .models import Role, RoleKind, RoleType, validate_roles
from .permissions import UserRuleMode
from .settings import (
    ALARMO_STATES,
    DIRECTIONS,
    KEY_ALARM_SENSORS,
    KEY_CHARGING_SENSORS,
    KEY_DURATION_MIN,
    KEY_EARLIEST,
    KEY_END,
    KEY_METHODS,
    KEY_MOTION_SENSORS,
    KEY_SLEEP_SENSORS,
    KEY_START,
    KEY_TIME,
    KEY_UNTIL,
    NOTIFY_EVENTS,
    VACATION_STRATEGIES,
    AutoSettings,
    parse_integration_settings,
    parse_settings,
)

CONF_ROLE = "role"
CONF_NAME = "name"
CONF_ENABLED = "enabled"
MIRROR_FIELD = "mirror_to_old_input_select"
MIRROR_OVERLAYS_FIELD = "mirror_overlays"
CONF_DIRECTION = "direction"
DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
CONF_USER = "user"
CONF_USER_MODE = "mode"
CONF_USER_ROLES = "roles"
CONF_ENTER_ACTIONS = "enter_actions"
CONF_EXIT_ACTIONS = "exit_actions"


def build_preset_roles(preset: str) -> list[dict[str, Any]]:
    """Return the stored role list for a preset."""
    enabled = PRESET_ENABLED_ROLES[preset]
    return [
        Role(role_id, DEFAULT_ROLE_NAMES[role_id], role_id in enabled).to_dict()
        for role_id in DEFAULT_ROLE_ORDER
    ]


def _role_selector(roles: list[Role]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=r.id, label=r.name) for r in roles],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class HomeModesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup (one entry per household)."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose a preset."""
        if user_input is not None:
            preset = user_input[CONF_PRESET]
            return self.async_create_entry(
                title=TITLE,
                data={CONF_PRESET: preset},
                options={CONF_ROLES: build_preset_roles(preset)},
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_PRESET, default=PRESET_SIMPLE): SelectSelector(
                    SelectSelectorConfig(
                        options=list(PRESETS),
                        mode=SelectSelectorMode.LIST,
                        translation_key="preset",
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HomeModesOptionsFlow:
        """Return the options flow."""
        return HomeModesOptionsFlow()


class HomeModesOptionsFlow(OptionsFlowWithReload):
    """Rename, reorder, toggle roles and manage custom modes."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._roles: list[Role] | None = None
        self._editing: str | None = None
        self._extra: dict[str, Any] | None = None
        self._alarmo: dict[str, Any] = {}
        self._map_index = 0
        self._import_entity: str | None = None
        self._import_options: list[str] = []
        self._import_mapping: dict[str, str] = {}
        self._import_mirror = False
        self._import_mirror_overlays = False

    def _saved_roles(self) -> list[Role]:
        """Return the roles as stored (the import never uses unsaved edits)."""
        return [Role.from_dict(raw) for raw in self.config_entry.options[CONF_ROLES]]

    @property
    def extra(self) -> dict[str, Any]:
        """Return the working copy of every option except the roles."""
        if self._extra is None:
            self._extra = {k: v for k, v in self.config_entry.options.items() if k != CONF_ROLES}
        return self._extra

    @property
    def settings(self) -> AutoSettings:
        """Return the settings parsed from the working copy."""
        return parse_settings(self.extra)

    @property
    def roles(self) -> list[Role]:
        """Return the working copy of the roles."""
        if self._roles is None:
            self._roles = [Role.from_dict(raw) for raw in self.config_entry.options[CONF_ROLES]]
        return self._roles

    def _custom_ids(self) -> list[str]:
        return [r.id for r in self.roles if r.type is RoleType.CUSTOM]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options menu."""
        menu = ["edit_role", "move_role", "presence", "night", "morning", "override", "user_rules"]
        if len(self._custom_ids()) < MAX_CUSTOM_MODES:
            menu.append("add_custom")
        if self._custom_ids():
            menu.append("remove_custom")
        menu.extend(["integrations", "save"])
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_integrations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sub-menu for actions, Alarmo, vacation simulation, notifications and history."""
        return self.async_show_menu(
            step_id="integrations",
            menu_options=[
                "actions",
                "alarmo",
                "vacation",
                "notify",
                "history",
                "import_input_select",
                "init",
            ],
        )

    # --- import from input_select (migration helper) -------------------------

    async def async_step_import_input_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the old input_select. Nothing is written in this or the next step."""
        errors: dict[str, str] = {}
        current = parse_integration_settings(self.extra).mirror
        if user_input is not None:
            options = input_select_options(self.hass, user_input["entity_id"])
            if not options:
                errors["base"] = "input_select_empty"
            else:
                self._import_entity = user_input["entity_id"]
                self._import_options = options
                self._import_mapping = suggest_mapping(options, self._saved_roles())
                self._import_mirror = current.enabled and current.entity_id == self._import_entity
                self._import_mirror_overlays = current.overlays
                return await self.async_step_import_map()
        schema = vol.Schema(
            {
                vol.Required("entity_id", default=current.entity_id or vol.UNDEFINED): (
                    EntitySelector(EntitySelectorConfig(domain="input_select"))
                )
            }
        )
        return self.async_show_form(
            step_id="import_input_select", data_schema=schema, errors=errors
        )

    async def async_step_import_map(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm or change the suggested target of every option."""
        errors: dict[str, str] = {}
        placeholders = {"entity_id": self._import_entity or "", "problems": ""}
        if user_input is not None:
            self._import_mirror = bool(user_input.get(MIRROR_FIELD, False))
            self._import_mirror_overlays = bool(user_input.get(MIRROR_OVERLAYS_FIELD, False))
            self._import_mapping = {o: user_input[o] for o in self._import_options}
            plan = build_plan(self._saved_roles(), self._import_options, self._import_mapping)
            if plan.valid:
                return await self.async_step_import_confirm()
            errors["base"] = "import_invalid"
            placeholders["problems"] = ", ".join(plan.errors)
        choices = [
            SelectOptionDict(value=r.id, label=f"{r.name} ({r.id})")
            for r in self._saved_roles()
            if r.kind is not RoleKind.DERIVED
        ]
        choices += [
            SelectOptionDict(value=TARGET_CUSTOM, label="New custom mode (keep this name)"),
            SelectOptionDict(value=TARGET_SKIP, label="Skip this option"),
        ]
        fields: dict[Any, Any] = {
            vol.Required(option, default=self._import_mapping.get(option, TARGET_SKIP)): (
                SelectSelector(
                    SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
                )
            )
            for option in self._import_options
        }
        fields[vol.Required(MIRROR_FIELD, default=self._import_mirror)] = BooleanSelector()
        fields[vol.Required(MIRROR_OVERLAYS_FIELD, default=self._import_mirror_overlays)] = (
            BooleanSelector()
        )
        return self.async_show_form(
            step_id="import_map",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_import_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the preview and the usage report; write only after confirmation."""
        entity = self._import_entity or ""
        plan = build_plan(self._saved_roles(), self._import_options, self._import_mapping)
        if user_input is not None:
            if user_input["confirm"] and plan.valid:
                # Only the import is saved: it is applied to the options as stored, never to
                # the working copy, so unrelated pending edits of this session are dropped.
                saved = dict(self.config_entry.options)
                return self.async_create_entry(
                    data=apply_plan_options(
                        saved, plan, entity, self._import_mirror, self._import_mirror_overlays
                    )
                )
            return await self.async_step_integrations()
        usage = usage_report(self.hass, entity, self._import_options)
        snippets = replacement_snippets(self.hass, self.config_entry.entry_id, entity, plan)
        used = [
            f"{label}: {', '.join(str(i.get('entity_id') or i.get('name')) for i in items)}"
            for label, items in usage.items()
            if items
        ]
        example = f"```yaml\n{snippets[0]['condition']}\n```" if snippets else ""
        return self.async_show_form(
            step_id="import_confirm",
            data_schema=vol.Schema({vol.Required("confirm", default=False): BooleanSelector()}),
            description_placeholders={
                "entity_id": entity,
                "preview": describe_plan(plan),
                "mirror": "on" if self._import_mirror else "off",
                "mirror_overlays": "on" if self._import_mirror_overlays else "off",
                "usage": "\n".join(f"- {u}" for u in used) or "- nothing found",
                "example": example,
            },
        )

    # --- enter / exit actions -----------------------------------------------

    async def async_step_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the role whose actions are edited, and the per-action timeout."""
        current = parse_integration_settings(self.extra)
        if user_input is not None:
            self.extra[CONF_ACTIONS_TIMEOUT] = user_input[CONF_ACTIONS_TIMEOUT]
            self._editing = user_input[CONF_ROLE]
            return await self.async_step_actions_edit()
        schema = vol.Schema(
            {
                vol.Required(CONF_ROLE): _role_selector(self.roles),
                vol.Required(CONF_ACTIONS_TIMEOUT, default=current.actions_timeout): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=600,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="actions", data_schema=schema)

    async def async_step_actions_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the enter and exit actions of the picked role."""
        index = next(i for i, r in enumerate(self.roles) if r.id == self._editing)
        current = self.roles[index]
        errors: dict[str, str] = {}
        if user_input is not None:
            enter = list(user_input.get(CONF_ENTER_ACTIONS) or [])
            leave = list(user_input.get(CONF_EXIT_ACTIONS) or [])
            for key, value in ((CONF_ENTER_ACTIONS, enter), (CONF_EXIT_ACTIONS, leave)):
                try:
                    cv.SCRIPT_SCHEMA(value)
                except vol.Invalid:
                    errors[key] = "invalid_actions"
            if not errors:
                roles = list(self.roles)
                roles[index] = replace(
                    current,
                    enter_actions=tuple(dict(a) for a in enter),
                    exit_actions=tuple(dict(a) for a in leave),
                )
                self._roles = roles
                return await self.async_step_integrations()
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENTER_ACTIONS,
                    description={"suggested_value": [dict(a) for a in current.enter_actions]},
                ): ActionSelector(),
                vol.Optional(
                    CONF_EXIT_ACTIONS,
                    description={"suggested_value": [dict(a) for a in current.exit_actions]},
                ): ActionSelector(),
            }
        )
        return self.async_show_form(
            step_id="actions_edit",
            data_schema=schema,
            errors=errors,
            description_placeholders={"role": current.name},
        )

    # --- Alarmo bridge ------------------------------------------------------

    async def async_step_alarmo(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Alarmo bridge settings (off by default)."""
        current = parse_integration_settings(self.extra).alarmo
        if user_input is not None:
            self._alarmo = {
                "enabled": user_input["enabled"],
                "direction": user_input["direction"],
                "entity_id": user_input.get("entity_id") or None,
                "apply_auto": user_input["apply_auto"],
                "mappings": [],
            }
            self._map_index = 0
            if not user_input["enabled"]:
                self._alarmo["mappings"] = list(
                    (self.extra.get(CONF_ALARMO) or {}).get("mappings") or []
                )
                self.extra[CONF_ALARMO] = self._alarmo
                return await self.async_step_integrations()
            return await self._async_next_mapping()
        schema = vol.Schema(
            {
                vol.Required("enabled", default=current.enabled): BooleanSelector(),
                vol.Required("direction", default=current.direction): SelectSelector(
                    SelectSelectorConfig(
                        options=list(DIRECTIONS),
                        mode=SelectSelectorMode.LIST,
                        translation_key="alarmo_direction",
                    )
                ),
                vol.Optional(
                    "entity_id", description={"suggested_value": current.entity_id}
                ): EntitySelector(
                    EntitySelectorConfig(domain="alarm_control_panel", integration="alarmo")
                ),
                vol.Required("apply_auto", default=current.apply_auto): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="alarmo", data_schema=schema)

    async def _async_next_mapping(self) -> ConfigFlowResult:
        """Show the mapping form of the next Alarmo state, or finish."""
        if self._map_index >= len(ALARMO_STATES):
            self.extra[CONF_ALARMO] = self._alarmo
            return await self.async_step_integrations()
        state = ALARMO_STATES[self._map_index]
        if state == "disarmed":
            return await self.async_step_alarmo_map_disarmed()
        return await self.async_step_alarmo_map()

    async def async_step_alarmo_map(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Map one armed Alarmo state to a role."""
        return await self._async_mapping_form("alarmo_map", user_input)

    async def async_step_alarmo_map_disarmed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Map the disarmed state (with the explicit, off-by-default allow-disarm switch)."""
        return await self._async_mapping_form("alarmo_map_disarmed", user_input)

    async def _async_mapping_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        state = ALARMO_STATES[self._map_index]
        stored: dict[str, Any] = next(
            (
                m
                for m in (self.extra.get(CONF_ALARMO) or {}).get("mappings") or []
                if m.get("state") == state
            ),
            {},
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            role = user_input.get(CONF_ROLE) or None
            to_alarmo = bool(user_input.get("to_alarmo"))
            from_alarmo = bool(user_input.get("from_alarmo"))
            allow_disarm = bool(user_input.get("allow_disarm")) and to_alarmo
            if (to_alarmo or from_alarmo) and role is None:
                errors[CONF_ROLE] = "role_required"
            elif to_alarmo and any(
                m["role"] == role and m["to_alarmo"] for m in self._alarmo["mappings"]
            ):
                errors[CONF_ROLE] = "duplicate_role"
            if not errors:
                self._alarmo["mappings"].append(
                    {
                        "state": state,
                        "role": role,
                        "to_alarmo": to_alarmo,
                        "from_alarmo": from_alarmo,
                        "allow_disarm": allow_disarm if state == "disarmed" else False,
                    }
                )
                self._map_index += 1
                return await self._async_next_mapping()
        primaries = [r for r in self.roles if r.enabled and r.selectable_primary]
        fields: dict[Any, Any] = {
            vol.Optional(
                CONF_ROLE, description={"suggested_value": stored.get("role")}
            ): _role_selector(primaries),
            vol.Required("to_alarmo", default=bool(stored.get("to_alarmo"))): BooleanSelector(),
            vol.Required("from_alarmo", default=bool(stored.get("from_alarmo"))): BooleanSelector(),
        }
        if state == "disarmed":
            fields[vol.Required("allow_disarm", default=bool(stored.get("allow_disarm")))] = (
                BooleanSelector()
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"state": state},
        )

    # --- vacation simulation ------------------------------------------------

    async def async_step_vacation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Vacation simulation settings (off by default)."""
        current = parse_integration_settings(self.extra).vacation
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input["enabled"] and not user_input.get("lights"):
                errors["lights"] = "lights_required"
            if user_input["enabled"] and not user_input.get("roles"):
                errors["roles"] = "roles_required"
            if user_input["end"] <= user_input["start"]:
                errors["end"] = "window_same_day"
            if user_input["min_on_min"] > user_input["max_on_min"]:
                errors["max_on_min"] = "max_before_min"
            if not errors:
                self.extra[CONF_VACATION_SIM] = {
                    "enabled": user_input["enabled"],
                    "roles": list(user_input.get("roles") or []),
                    "strategy": user_input["strategy"],
                    "lights": list(user_input.get("lights") or []),
                    "start": user_input["start"],
                    "end": user_input["end"],
                    "min_on_min": user_input["min_on_min"],
                    "max_on_min": user_input["max_on_min"],
                    "min_gap_min": user_input["min_gap_min"],
                }
                return await self.async_step_integrations()

        def minutes(name: str, default: float, maximum: int) -> Any:
            return (
                vol.Required(name, default=default),
                NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=maximum,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            )

        primaries = [r for r in self.roles if r.selectable_primary]
        fields: dict[Any, Any] = {
            vol.Required("enabled", default=current.enabled): BooleanSelector(),
            vol.Optional("roles", default=list(current.roles)): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=r.id, label=r.name) for r in primaries],
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required("strategy", default=current.strategy): SelectSelector(
                SelectSelectorConfig(
                    options=list(VACATION_STRATEGIES),
                    mode=SelectSelectorMode.LIST,
                    translation_key="vacation_strategy",
                )
            ),
            vol.Optional("lights", default=list(current.lights)): EntitySelector(
                EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Required("start", default=current.start.isoformat()): TimeSelector(),
            vol.Required("end", default=current.end.isoformat()): TimeSelector(),
        }
        for name, default, maximum in (
            ("min_on_min", current.min_on.total_seconds() / 60, 720),
            ("max_on_min", current.max_on.total_seconds() / 60, 720),
            ("min_gap_min", current.min_gap.total_seconds() / 60, 720),
        ):
            key, selector = minutes(name, default, maximum)
            fields[key] = selector
        return self.async_show_form(
            step_id="vacation", data_schema=vol.Schema(fields), errors=errors
        )

    # --- notifications ------------------------------------------------------

    async def async_step_notify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Notification sub-menu."""
        menu = ["notify_add"]
        if parse_integration_settings(self.extra).notify.rules:
            menu.append("notify_remove")
        menu.extend(["notify_settings", "integrations"])
        return self.async_show_menu(step_id="notify", menu_options=menu)

    def _notify_options(self) -> dict[str, Any]:
        raw = self.extra.get(CONF_NOTIFY) or {}
        return {"rules": list(raw.get("rules") or []), "rate_limit_s": raw.get("rate_limit_s")}

    async def async_step_notify_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a notification rule."""
        errors: dict[str, str] = {}
        if user_input is not None:
            event = user_input["event"]
            targets = list(user_input.get("targets") or [])
            services = list(user_input.get("services") or [])
            if event == "changed_to" and not user_input.get(CONF_ROLE):
                errors[CONF_ROLE] = "role_required"
            if not targets and not services:
                errors["targets"] = "no_target"
            for key in ("message", "title"):
                text = user_input.get(key) or ""
                if text:
                    try:
                        Template(text, self.hass).ensure_valid()
                    except TemplateError:
                        errors[key] = "template_invalid"
            if not errors:
                options = self._notify_options()
                options["rules"].append(
                    {
                        "event": event,
                        "role": user_input.get(CONF_ROLE) if event == "changed_to" else None,
                        "targets": targets,
                        "services": services,
                        "message": user_input.get("message") or "",
                        "title": user_input.get("title") or "",
                    }
                )
                self.extra[CONF_NOTIFY] = options
                return await self.async_step_notify()
        services = sorted(
            name
            for name in self.hass.services.async_services_for_domain("notify")
            if name != "send_message"
        )
        schema = vol.Schema(
            {
                vol.Required("event"): SelectSelector(
                    SelectSelectorConfig(
                        options=list(NOTIFY_EVENTS),
                        mode=SelectSelectorMode.LIST,
                        translation_key="notify_event",
                    )
                ),
                vol.Optional(CONF_ROLE): _role_selector(self.roles),
                vol.Optional("targets", default=[]): EntitySelector(
                    EntitySelectorConfig(domain="notify", multiple=True)
                ),
                vol.Optional("services", default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=services,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional("message"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("title"): TextSelector(),
            }
        )
        return self.async_show_form(step_id="notify_add", data_schema=schema, errors=errors)

    async def async_step_notify_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a notification rule."""
        options = self._notify_options()
        if user_input is not None:
            index = int(user_input["rule"])
            if 0 <= index < len(options["rules"]):
                del options["rules"][index]
            self.extra[CONF_NOTIFY] = options
            return await self.async_step_notify()
        labels = [
            SelectOptionDict(
                value=str(i),
                label=f"{r['event']}{' ' + r['role'] if r.get('role') else ''}: "
                + ", ".join([*(r.get("targets") or []), *(r.get("services") or [])]),
            )
            for i, r in enumerate(options["rules"])
        ]
        schema = vol.Schema(
            {
                vol.Required("rule"): SelectSelector(
                    SelectSelectorConfig(options=labels, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="notify_remove", data_schema=schema)

    async def async_step_notify_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Duplicate rate limit."""
        current = parse_integration_settings(self.extra).notify
        if user_input is not None:
            options = self._notify_options()
            options["rate_limit_s"] = user_input["rate_limit_s"]
            self.extra[CONF_NOTIFY] = options
            return await self.async_step_notify()
        schema = vol.Schema(
            {
                vol.Required("rate_limit_s", default=current.rate_limit.total_seconds()): (
                    NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=3600,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                )
            }
        )
        return self.async_show_form(step_id="notify_settings", data_schema=schema)

    # --- history ------------------------------------------------------------

    async def async_step_history(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """History size."""
        current = parse_integration_settings(self.extra).history_max
        if user_input is not None:
            self.extra[CONF_HISTORY] = {"max_entries": int(user_input["max_entries"])}
            return await self.async_step_integrations()
        schema = vol.Schema(
            {
                vol.Required("max_entries", default=current): NumberSelector(
                    NumberSelectorConfig(min=10, max=5000, step=10, mode=NumberSelectorMode.BOX)
                )
            }
        )
        return self.async_show_form(step_id="history", data_schema=schema)

    async def async_step_edit_role(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the role to edit."""
        if user_input is not None:
            self._editing = user_input[CONF_ROLE]
            return await self.async_step_edit_details()
        return self.async_show_form(
            step_id="edit_role",
            data_schema=vol.Schema({vol.Required(CONF_ROLE): _role_selector(self.roles)}),
        )

    async def async_step_edit_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the name and enabled flag of the picked role."""
        roles = self.roles
        index = next(i for i, r in enumerate(roles) if r.id == self._editing)
        current = roles[index]
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = list(roles)
            candidate[index] = replace(
                current, name=user_input[CONF_NAME].strip(), enabled=user_input[CONF_ENABLED]
            )
            if (error := validate_roles(candidate)) is None:
                self._roles = candidate
                return await self.async_step_init()
            errors["base"] = error
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=current.name): TextSelector(),
                vol.Required(CONF_ENABLED, default=current.enabled): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"role": current.name},
        )

    async def async_step_move_role(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move a role up or down in the order."""
        if user_input is not None:
            roles = list(self.roles)
            index = next(i for i, r in enumerate(roles) if r.id == user_input[CONF_ROLE])
            target = index - 1 if user_input[CONF_DIRECTION] == DIRECTION_UP else index + 1
            if 0 <= target < len(roles):
                roles[index], roles[target] = roles[target], roles[index]
                self._roles = roles
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(CONF_ROLE): _role_selector(self.roles),
                vol.Required(CONF_DIRECTION, default=DIRECTION_UP): SelectSelector(
                    SelectSelectorConfig(
                        options=[DIRECTION_UP, DIRECTION_DOWN],
                        mode=SelectSelectorMode.LIST,
                        translation_key="direction",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="move_role", data_schema=schema)

    async def async_step_add_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a user-defined custom mode (up to MAX_CUSTOM_MODES)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            used = set(self._custom_ids())
            free = next(
                (
                    f"{CUSTOM_PREFIX}{n}"
                    for n in range(1, MAX_CUSTOM_MODES + 1)
                    if f"{CUSTOM_PREFIX}{n}" not in used
                ),
                None,
            )
            if free is None:
                errors["base"] = "max_custom_modes"
            else:
                candidate = [*self.roles, Role(free, user_input[CONF_NAME].strip())]
                if (error := validate_roles(candidate)) is None:
                    self._roles = candidate
                    return await self.async_step_init()
                errors["base"] = error
        return self.async_show_form(
            step_id="add_custom",
            data_schema=vol.Schema({vol.Required(CONF_NAME): TextSelector()}),
            errors=errors,
        )

    async def async_step_remove_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a custom mode."""
        customs = [r for r in self.roles if r.type is RoleType.CUSTOM]
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = [r for r in self.roles if r.id != user_input[CONF_ROLE]]
            if (error := validate_roles(candidate)) is None:
                self._roles = candidate
                return await self.async_step_init()
            errors["base"] = error
        return self.async_show_form(
            step_id="remove_custom",
            data_schema=vol.Schema({vol.Required(CONF_ROLE): _role_selector(customs)}),
            errors=errors,
        )

    async def async_step_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the tracked persons and the presence timers."""
        current = self.settings
        if user_input is not None:
            self.extra[CONF_PERSONS] = list(user_input.get(CONF_PERSONS, []))
            self.extra[CONF_AWAY_DELAY_MIN] = user_input[CONF_AWAY_DELAY_MIN]
            self.extra[CONF_VACATION_AFTER_H] = user_input[CONF_VACATION_AFTER_H]
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Optional(CONF_PERSONS, default=list(current.persons)): EntitySelector(
                    EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Required(
                    CONF_AWAY_DELAY_MIN, default=current.away_delay.total_seconds() / 60
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=720,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_VACATION_AFTER_H, default=current.vacation_after.total_seconds() / 3600
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=720,
                        step=1,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="presence", data_schema=schema)

    async def async_step_night(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure the night methods (any combination)."""
        current = self.settings.night
        errors: dict[str, str] = {}
        if user_input is not None:
            methods = user_input.get(KEY_METHODS, [])
            if NIGHT_SLEEP_SENSORS in methods and not user_input.get(KEY_SLEEP_SENSORS):
                errors[KEY_SLEEP_SENSORS] = "sensors_required"
            if NIGHT_PHONE_CHARGING in methods and not user_input.get(KEY_CHARGING_SENSORS):
                errors[KEY_CHARGING_SENSORS] = "sensors_required"
            if user_input[KEY_START] == user_input[KEY_END]:
                errors[KEY_END] = "window_empty"
            if not errors:
                self.extra[CONF_NIGHT] = {
                    KEY_METHODS: list(methods),
                    KEY_START: user_input[KEY_START],
                    KEY_END: user_input[KEY_END],
                    KEY_SLEEP_SENSORS: list(user_input.get(KEY_SLEEP_SENSORS, [])),
                    KEY_CHARGING_SENSORS: list(user_input.get(KEY_CHARGING_SENSORS, [])),
                }
                return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Optional(KEY_METHODS, default=sorted(current.methods)): SelectSelector(
                    SelectSelectorConfig(
                        options=list(NIGHT_METHODS),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="night_methods",
                    )
                ),
                vol.Required(KEY_START, default=current.start.isoformat()): TimeSelector(),
                vol.Required(KEY_END, default=current.end.isoformat()): TimeSelector(),
                vol.Optional(
                    KEY_SLEEP_SENSORS, default=list(current.sleep_sensors)
                ): EntitySelector(EntitySelectorConfig(domain="binary_sensor", multiple=True)),
                vol.Optional(
                    KEY_CHARGING_SENSORS, default=list(current.charging_sensors)
                ): EntitySelector(
                    EntitySelectorConfig(domain=["binary_sensor", "sensor"], multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="night", data_schema=schema, errors=errors)

    async def async_step_morning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the morning methods (any combination)."""
        current = self.settings.morning
        errors: dict[str, str] = {}
        if user_input is not None:
            methods = user_input.get(KEY_METHODS, [])
            if MORNING_MOTION in methods and not user_input.get(KEY_MOTION_SENSORS):
                errors[KEY_MOTION_SENSORS] = "sensors_required"
            if MORNING_ALARM in methods and not user_input.get(KEY_ALARM_SENSORS):
                errors[KEY_ALARM_SENSORS] = "sensors_required"
            if not errors:
                self.extra[CONF_MORNING] = {
                    KEY_METHODS: list(methods),
                    KEY_TIME: user_input[KEY_TIME],
                    KEY_EARLIEST: user_input[KEY_EARLIEST],
                    KEY_MOTION_SENSORS: list(user_input.get(KEY_MOTION_SENSORS, [])),
                    KEY_ALARM_SENSORS: list(user_input.get(KEY_ALARM_SENSORS, [])),
                }
                return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Optional(KEY_METHODS, default=sorted(current.methods)): SelectSelector(
                    SelectSelectorConfig(
                        options=list(MORNING_METHODS),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="morning_methods",
                    )
                ),
                vol.Required(KEY_TIME, default=current.at.isoformat()): TimeSelector(),
                vol.Required(KEY_EARLIEST, default=current.earliest.isoformat()): TimeSelector(),
                vol.Optional(
                    KEY_MOTION_SENSORS, default=list(current.motion_sensors)
                ): EntitySelector(EntitySelectorConfig(domain="binary_sensor", multiple=True)),
                vol.Optional(
                    KEY_ALARM_SENSORS, default=list(current.alarm_sensors)
                ): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="timestamp", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="morning", data_schema=schema, errors=errors)

    async def async_step_override(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure how long a manual override lasts."""
        current = self.settings.override
        if user_input is not None:
            self.extra[CONF_OVERRIDE] = {
                KEY_UNTIL: user_input[KEY_UNTIL],
                KEY_DURATION_MIN: user_input[KEY_DURATION_MIN],
            }
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(KEY_UNTIL, default=current.until): SelectSelector(
                    SelectSelectorConfig(
                        options=list(UNTIL_MODES),
                        mode=SelectSelectorMode.LIST,
                        translation_key="override_until",
                    )
                ),
                vol.Required(
                    KEY_DURATION_MIN, default=current.duration.total_seconds() / 60
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=10080,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="override", data_schema=schema)

    async def async_step_user_rules(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the permission rule of one Home Assistant user."""
        users = [
            u
            for u in await self.hass.auth.async_get_users()
            if u.is_active and not u.system_generated
        ]
        if user_input is not None:
            rules = dict(self.extra.get(CONF_USER_RULES) or {})
            mode = user_input[CONF_USER_MODE]
            roles = (
                list(user_input.get(CONF_USER_ROLES, [])) if mode == UserRuleMode.ALLOW_LIST else []
            )
            rules[user_input[CONF_USER]] = {"mode": mode, "roles": roles}
            self.extra[CONF_USER_RULES] = rules
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(CONF_USER): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=u.id, label=u.name or u.id) for u in users],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_USER_MODE, default=UserRuleMode.UNRESTRICTED): SelectSelector(
                    SelectSelectorConfig(
                        options=[m.value for m in UserRuleMode],
                        mode=SelectSelectorMode.LIST,
                        translation_key="user_rule_mode",
                    )
                ),
                vol.Optional(CONF_USER_ROLES, default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=r.id, label=r.name)
                            for r in self.roles
                            if r.enabled
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user_rules", data_schema=schema)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Save the options (the entry reloads if they changed)."""
        return self.async_create_entry(
            data={**self.extra, CONF_ROLES: [role.to_dict() for role in self.roles]}
        )
