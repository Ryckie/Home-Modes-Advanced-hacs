"""Serve the Lovelace cards and load them on every dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, FRONTEND_MODULE, FRONTEND_URL_BASE

_LOGGER = logging.getLogger(__name__)
DATA_FRONTEND = f"{DOMAIN}_frontend_registered"
FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_module_url(hass: HomeAssistant) -> str:
    """Return the module URL with the integration version as cache-buster."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"{FRONTEND_URL_BASE}/{FRONTEND_MODULE}?v={integration.version}"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the static path and the module (once; safe to call again)."""
    if hass.data.get(DATA_FRONTEND):
        return
    hass.data[DATA_FRONTEND] = True
    if getattr(hass, "http", None) is None:
        _LOGGER.debug("The HTTP component is not available; cards are not served")
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=True)]
    )
    url = await async_module_url(hass)
    try:
        from homeassistant.components.frontend import (
            DATA_EXTRA_MODULE_URL,
            add_extra_js_url,
        )
    except ImportError:
        _LOGGER.debug("The frontend is not installed; cards are served but not auto-loaded")
        return
    if DATA_EXTRA_MODULE_URL not in hass.data:
        _LOGGER.debug("The frontend is not set up; cards are served but not auto-loaded")
        return
    add_extra_js_url(hass, url)
