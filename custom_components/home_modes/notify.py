"""User-defined notifications for mode changes, denied attempts and bridge errors."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import EVENT_DENIED, ROLE_GUEST, ROLE_VACATION
from .coordinator import HomeModesCoordinator
from .engine import ChangeEngine
from .models import Change, ChangeKind, PipelineStage
from .settings import NotifyRule
from .template_vars import role_name, role_variables

if TYPE_CHECKING:
    from .history import HistoryLog

_LOGGER = logging.getLogger(__name__)

CHANNEL_MODE_CHANGES = "HM_ModeChanges"
CHANNEL_ALERTS = "HM_Alerts"
CHANNEL_GUESTS = "HM_Guests"

EVENT_ANY_CHANGE = "any_change"
EVENT_CHANGED_TO = "changed_to"
EVENT_DENIED_ATTEMPT = "denied"
EVENT_BRIDGE_ERROR = "bridge_error"
EVENT_VACATION = "vacation_entered"
EVENT_GUEST_ON = "guest_on"

# event -> (Android channel, Android importance, iOS interruption level)
_PROFILES: dict[str, tuple[str, str, str]] = {
    EVENT_ANY_CHANGE: (CHANNEL_MODE_CHANGES, "low", "passive"),
    EVENT_CHANGED_TO: (CHANNEL_MODE_CHANGES, "low", "passive"),
    EVENT_VACATION: (CHANNEL_MODE_CHANGES, "low", "passive"),
    EVENT_GUEST_ON: (CHANNEL_GUESTS, "default", "active"),
    EVENT_DENIED_ATTEMPT: (CHANNEL_ALERTS, "high", "time-sensitive"),
    EVENT_BRIDGE_ERROR: (CHANNEL_ALERTS, "high", "time-sensitive"),
}
SEND_TIMEOUT_S = 30
REASON_RATE_LIMIT = "rate_limited"
REASON_SPECIFIC = "most_specific_rule_wins"
MOBILE_APP = "mobile_app"


def _mask(target: str) -> str:
    """Return a shortened target for logs (full notification targets are never logged)."""
    return f"{target[:8]}…" if len(target) > 8 else target


def build_payload(event: str, message: str, title: str) -> dict[str, Any]:
    """Return the data of a legacy notify service call (Companion app fields)."""
    channel, importance, level = _PROFILES[event]
    return {
        "message": message,
        "title": title or "Home Modes",
        "data": {
            "channel": channel,  # Android
            "importance": importance,  # Android
            "group": channel,  # iOS thread and Android group: one stack per channel
            "push": {"interruption-level": level},  # iOS
        },
    }


def mobile_app_call(hass: HomeAssistant, entity_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return (notify service, extra data) for a Companion app notify entity, else None."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != MOBILE_APP or not entry.config_entry_id:
        return None
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if config_entry is None:
        return None
    device_name = config_entry.data.get("device_name")
    webhook_id = config_entry.data.get("webhook_id")
    if device_name:
        service = f"{MOBILE_APP}_{slugify(device_name)}"
        if hass.services.has_service("notify", service):
            return service, {}
    if webhook_id and hass.services.has_service("notify", MOBILE_APP):
        return MOBILE_APP, {"target": [webhook_id]}
    return None


def delivery_calls(
    hass: HomeAssistant, event: str, rule: NotifyRule, message: str, title: str
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return one (target, notify service, service data) per target of the rule."""
    calls: list[tuple[str, str, dict[str, Any]]] = []
    for entity_id in rule.targets:
        # notify.send_message carries only message and title, so a Companion app
        # entity would land in the app's default channel ("General"). Send to the
        # same phone through its mobile_app service, with the channel data.
        if (mobile := mobile_app_call(hass, entity_id)) is not None:
            service, extra = mobile
            calls.append((entity_id, service, {**build_payload(event, message, title), **extra}))
            continue
        data: dict[str, Any] = {"entity_id": entity_id, "message": message}
        if title:
            data["title"] = title
        calls.append((entity_id, "send_message", data))
    for service in rule.services:
        calls.append((f"notify.{service}", service, build_payload(event, message, title)))
    return calls


async def async_send_test(hass: HomeAssistant, rule: NotifyRule) -> list[tuple[str, str | None]]:
    """Send a test message to every target of the rule, with the rule's channel.

    Ignores the duplicate rate limit. Returns (target, error) per target; error is None
    when the call succeeded.
    """
    message = "Test notification from Home Modes. This rule's targets receive it."
    results: list[tuple[str, str | None]] = []
    for target, service, data in delivery_calls(hass, rule.event, rule, message, "Home Modes"):
        try:
            async with asyncio.timeout(SEND_TIMEOUT_S):
                await hass.services.async_call("notify", service, data, blocking=True)
        except Exception as err:  # shown to the admin, never raised
            results.append((target, str(err) or type(err).__name__))
        else:
            results.append((target, None))
    return results


class Notifier:
    """Sends notifications according to the user's rules (none by default)."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HomeModesCoordinator,
        engine: ChangeEngine,
        history: HistoryLog,
    ) -> None:
        """Initialize the notifier."""
        self.hass = hass
        self.coordinator = coordinator
        self.engine = engine
        self.history = history
        self._unsubs: list[Callable[[], None]] = []
        # (target, message) -> (time, batch, event); a batch is one change or one event
        self._last_sent: dict[tuple[str, str], tuple[datetime, int, str]] = {}
        self._batch = 0

    @property
    def _rules(self) -> tuple[NotifyRule, ...]:
        return self.coordinator.integrations.notify.rules

    @callback
    def async_setup(self) -> None:
        """Register the pipeline hook and the denied-event listener."""
        self._unsubs.append(self.engine.async_register_hook(PipelineStage.NOTIFY, self._on_change))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_DENIED, self._on_denied))

    @callback
    def async_unload(self) -> None:
        """Unregister."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # --- event sources ------------------------------------------------------

    async def _user(self, user_id: str | None) -> str:
        if not user_id:
            return ""
        user = await self.hass.auth.async_get_user(user_id)
        return (user.name if user and user.name else user_id) or ""

    def _variables(
        self,
        *,
        from_role: str | None,
        to_role: str | None,
        role: str | None,
        source: str | None,
        rule: str | None,
        user: str,
        at: datetime,
    ) -> dict[str, Any]:
        return {
            **role_variables(self.coordinator, from_role, to_role),
            "role": role or "",
            "role_name": role_name(self.coordinator, role),
            "source": source or "",
            "rule": rule or "",
            "user": user,
            "time": dt_util.as_local(at).strftime("%H:%M"),
        }

    async def _on_change(self, change: Change) -> None:
        if not self._rules:
            return
        variables = self._variables(
            from_role=change.from_role,
            to_role=change.to_role,
            role=change.role,
            source=change.source.value,
            rule=change.rule,
            user=await self._user(change.user_id),
            at=change.at,
        )
        # Most specific first: when several rules would send the same text to the same
        # target, the duplicate rate limit keeps the most specific one (and its channel).
        self._batch += 1
        batch = self._batch
        events: list[tuple[str, str | None]] = []
        if change.kind is ChangeKind.OVERLAY and change.to_role == ROLE_GUEST:
            events.append((EVENT_GUEST_ON, None))
        if change.kind is ChangeKind.PRIMARY and change.to_role == ROLE_VACATION:
            events.append((EVENT_VACATION, None))
        if change.to_role is not None:
            events.append((EVENT_CHANGED_TO, change.to_role))
        events.append((EVENT_ANY_CHANGE, None))
        for event, role_filter in events:
            default = f"Home mode: {variables['from_name'] or '-'} → {variables['to_name']}"
            if change.kind is ChangeKind.OVERLAY:
                state = "on" if change.to_role else "off"
                default = f"{variables['role_name']} turned {state}"
            self._dispatch(event, variables, default, role_filter, batch)

    async def _on_denied(self, event: Event) -> None:
        if not self._rules:
            return
        data = event.data
        variables = self._variables(
            from_role=None,
            to_role=data.get("role"),
            role=data.get("role"),
            source=data.get("source"),
            rule=data.get("reason"),
            user=await self._user(data.get("user_id")),
            at=dt_util.utcnow(),
        )
        default = (
            f"Denied: {variables['user'] or 'a user'} tried to change "
            f"{variables['to_name'] or 'the auto switch'} ({variables['rule']})"
        )
        self._batch += 1
        self._dispatch(EVENT_DENIED_ATTEMPT, variables, default, None, self._batch)

    @callback
    def async_bridge_error(self, detail: str) -> None:
        """Notify about an Alarmo bridge error."""
        if not self._rules:
            return
        variables = self._variables(
            from_role=None,
            to_role=None,
            role=None,
            source="alarmo",
            rule=detail,
            user="",
            at=dt_util.utcnow(),
        )
        self._batch += 1
        self._dispatch(EVENT_BRIDGE_ERROR, variables, f"Alarmo bridge: {detail}", None, self._batch)

    # --- delivery -----------------------------------------------------------

    @callback
    def _dispatch(
        self,
        event: str,
        variables: dict[str, Any],
        default: str,
        role_filter: str | None,
        batch: int,
    ) -> None:
        for rule in self._rules:
            if rule.event != event:
                continue
            if event == EVENT_CHANGED_TO and rule.role != role_filter:
                continue
            if not rule.targets and not rule.services:
                continue  # no targets picked: stays off
            message = self._render(rule.message, variables, default)
            title = self._render(rule.title, variables, "")
            self.coordinator.config_entry.async_create_task(
                self.hass, self._async_send(event, rule, message, title, batch)
            )

    def _render(self, text: str, variables: dict[str, Any], default: str) -> str:
        if not text.strip():
            return default
        try:
            rendered = Template(text, self.hass).async_render(variables, parse_result=False)
        except TemplateError as err:
            _LOGGER.warning(
                "Notification template failed (%s), using the default text", type(err).__name__
            )
            return default
        # a message that renders empty (for example an unknown variable) is not sent empty
        return rendered if rendered.strip() or not default else default

    def _suppressed_reason(self, target: str, message: str, event: str, batch: int) -> str | None:
        """Return why this message must not be sent now (None: send it) and remember it."""
        now = dt_util.utcnow()
        limit = self.coordinator.integrations.notify.rate_limit
        for key, (at, old_batch, _) in list(self._last_sent.items()):
            if now - at >= limit and old_batch != batch:
                del self._last_sent[key]
        key = (target, message)
        previous = self._last_sent.get(key)
        if previous is not None:
            # same change or event: another, more specific rule already sent it
            return REASON_SPECIFIC if previous[1] == batch else REASON_RATE_LIMIT
        self._last_sent[key] = (now, batch, event)
        return None

    async def _async_send(
        self, event: str, rule: NotifyRule, message: str, title: str, batch: int
    ) -> None:
        for target, service, data in delivery_calls(self.hass, event, rule, message, title):
            if self._allow(target, message, event, batch):
                # logs mask the bare service name, as before (never the full target)
                label = service if target == f"notify.{service}" else target
                await self._async_call(service, data, label)

    def _allow(self, target: str, message: str, event: str, batch: int) -> bool:
        reason = self._suppressed_reason(target, message, event, batch)
        if reason is None:
            return True
        _LOGGER.debug("Notification suppressed (%s) for a %s rule", reason, event)
        # never silent: the history shows the reason and the target (admins only)
        self.history.async_add_system(
            "notification_suppressed", {"reason": reason, "target": target, "event": event}
        )
        return False

    async def _async_call(self, service: str, data: dict[str, Any], target: str) -> None:
        try:
            async with asyncio.timeout(SEND_TIMEOUT_S):
                await self.hass.services.async_call("notify", service, data, blocking=True)
        except Exception as err:
            _LOGGER.warning("Notification to %s failed (%s)", _mask(target), type(err).__name__)
