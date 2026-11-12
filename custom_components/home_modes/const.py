"""Constants for Home Modes Advanced."""

from __future__ import annotations

from datetime import timedelta
from types import MappingProxyType
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "home_modes"
TITLE: Final = "Home Modes"
DEVICE_NAME: Final = "Home Mode"
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Storage format. Steps 2 to 5 all wrote 1.1: every later field is optional with a default,
# so old files load unchanged. Bump the minor version for additive changes that need a
# migration step and the major version for incompatible ones (older code then refuses the
# file instead of guessing). Same for the config entry (VERSION / MINOR_VERSION in
# config_flow.py).
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 1.0

# Config entry data / options keys
CONF_PRESET: Final = "preset"
CONF_ROLES: Final = "roles"
CONF_USER_RULES: Final = "user_rules"
CONF_PERSONS: Final = "persons"
CONF_AWAY_DELAY_MIN: Final = "away_delay_min"
CONF_VACATION_AFTER_H: Final = "vacation_after_h"
CONF_NIGHT: Final = "night"
CONF_MORNING: Final = "morning"
CONF_OVERRIDE: Final = "override"
CONF_ACTIONS_TIMEOUT: Final = "actions_timeout_s"
CONF_ALARMO: Final = "alarmo"
CONF_VACATION_SIM: Final = "vacation_sim"
CONF_NOTIFY: Final = "notify"
CONF_HISTORY: Final = "history"

DEFAULT_ACTIONS_TIMEOUT_S: Final = 30
ACTION_LOOP_MAX: Final = 3
ACTION_LOOP_WINDOW: Final = timedelta(seconds=60)
DEFAULT_HISTORY_MAX: Final = 500
DEFAULT_NOTIFY_RATE_LIMIT_S: Final = 10

DEFAULT_AWAY_DELAY_MIN: Final = 4
DEFAULT_VACATION_AFTER_H: Final = 24
DEFAULT_OVERRIDE_DURATION_MIN: Final = 60
DEFAULT_NIGHT_START: Final = "22:00:00"
DEFAULT_NIGHT_END: Final = "06:00:00"
DEFAULT_MORNING_TIME: Final = "07:00:00"
DEFAULT_MORNING_EARLIEST: Final = "05:00:00"

# Night methods
NIGHT_TIME_WINDOW: Final = "time_window"
NIGHT_SLEEP_SENSORS: Final = "sleep_sensors"
NIGHT_PHONE_CHARGING: Final = "phone_charging"
NIGHT_MANUAL: Final = "manual"
NIGHT_METHODS: Final = (NIGHT_TIME_WINDOW, NIGHT_SLEEP_SENSORS, NIGHT_PHONE_CHARGING, NIGHT_MANUAL)
# Morning methods
MORNING_TIME: Final = "time"
MORNING_MOTION: Final = "motion"
MORNING_ALARM: Final = "alarm"
MORNING_MANUAL: Final = "manual"
MORNING_METHODS: Final = (MORNING_TIME, MORNING_MOTION, MORNING_ALARM, MORNING_MANUAL)
# Override end modes
UNTIL_END_OF_DAY: Final = "end_of_day"
UNTIL_NEXT_AUTO: Final = "next_auto"
UNTIL_DURATION: Final = "duration"
UNTIL_SET_AUTO: Final = "set_auto"
UNTIL_MODES: Final = (UNTIL_END_OF_DAY, UNTIL_NEXT_AUTO, UNTIL_DURATION, UNTIL_SET_AUTO)
DEFAULT_OVERRIDE_UNTIL: Final = UNTIL_NEXT_AUTO

PRESET_SIMPLE: Final = "simple"
PRESET_EXTENDED: Final = "extended"
PRESETS: Final = (PRESET_SIMPLE, PRESET_EXTENDED)

# Role ids of the built-in roles, in default display order.
ROLE_HOME: Final = "home"
ROLE_NIGHT: Final = "night"
ROLE_AWAY: Final = "away"
ROLE_VACATION: Final = "vacation"
ROLE_ALL_HOME: Final = "all_home"
ROLE_ALL_AWAY: Final = "all_away"
ROLE_GUEST: Final = "guest"
ROLE_DND: Final = "dnd"
CUSTOM_PREFIX: Final = "custom_"
MAX_CUSTOM_MODES: Final = 10

DEFAULT_ROLE_ORDER: Final = (
    ROLE_HOME,
    ROLE_NIGHT,
    ROLE_AWAY,
    ROLE_VACATION,
    ROLE_ALL_HOME,
    ROLE_ALL_AWAY,
    ROLE_GUEST,
    ROLE_DND,
)
DEFAULT_ROLE_NAMES: Final = MappingProxyType(
    {
        ROLE_HOME: "Home",
        ROLE_NIGHT: "Night",
        ROLE_AWAY: "Away",
        ROLE_VACATION: "Vacation",
        ROLE_ALL_HOME: "All home",
        ROLE_ALL_AWAY: "All away",
        ROLE_GUEST: "Guest",
        ROLE_DND: "Do not disturb",
    }
)
PRESET_ENABLED_ROLES: Final = MappingProxyType(
    {
        PRESET_SIMPLE: frozenset({ROLE_HOME, ROLE_NIGHT, ROLE_AWAY, ROLE_VACATION}),
        PRESET_EXTENDED: frozenset(
            {
                ROLE_HOME,
                ROLE_NIGHT,
                ROLE_AWAY,
                ROLE_VACATION,
                ROLE_ALL_HOME,
                ROLE_ALL_AWAY,
                ROLE_GUEST,
                ROLE_DND,
            }
        ),
    }
)

# Events
EVENT_CHANGED: Final = "home_modes_changed"
EVENT_DENIED: Final = "home_modes_denied"

# Services
SERVICE_SET_MODE: Final = "set_mode"
SERVICE_SET_OVERLAY: Final = "set_overlay"
SERVICE_REVERT: Final = "revert"
SERVICE_SET_TEMPORARY: Final = "set_temporary"
SERVICE_SET_AUTO: Final = "set_auto"
SERVICE_CLEAR_HISTORY: Final = "clear_history"
WS_HISTORY: Final = "home_modes/history"
WS_ALLOWED_ROLES: Final = "home_modes/allowed_roles"
SERVICE_IMPORT_INPUT_SELECT: Final = "import_input_select"

CONF_MIRROR: Final = "mirror"

INTENT_SET_MODE: Final = "HomeModesSetMode"
INTENT_SET_OVERLAY: Final = "HomeModesSetOverlay"

# Frontend: static files are served under this URL path (see frontend.py).
FRONTEND_URL_BASE: Final = "/home_modes_static"
FRONTEND_MODULE: Final = "home-modes-cards.js"

# Default icons per role type (the cards use them unless the card config overrides them).
ROLE_ICONS: Final = MappingProxyType(
    {
        "home": "mdi:home",
        "night": "mdi:weather-night",
        "away": "mdi:home-export-outline",
        "vacation": "mdi:palm-tree",
        "guest": "mdi:account-multiple",
        "dnd": "mdi:bell-off",
        "custom": "mdi:star-circle",
        "all_home": "mdi:home-group",
        "all_away": "mdi:home-off",
    }
)
ATTR_OVERRIDE_FLAG: Final = "override"
ATTR_DURATION: Final = "duration"
ATTR_MODE: Final = "mode"
ATTR_OVERLAY: Final = "overlay"
ATTR_ACTIVE: Final = "active"

# Entity unique id keys (prefixed with the config entry id)
KEY_SELECT: Final = "select"
KEY_SINCE: Final = "since"
KEY_PREVIOUS: Final = "previous"
KEY_TRIGGER_REASON: Final = "trigger_reason"
KEY_AUTO: Final = "auto"
KEY_ROLE_BINARY_SENSOR: Final = "role_"
KEY_ROLE_OVERLAY_SWITCH: Final = "overlay_"
