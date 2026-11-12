"""Static files: served, cache-busted with the integration version, and free of risky patterns."""

from __future__ import annotations

import json
import re
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.core import HomeAssistant

from .helpers import setup_entry

ROOT = Path(__file__).parents[1] / "custom_components" / "home_modes"
JS = ROOT / "frontend" / "home-modes-cards.js"
VERSION = json.loads((ROOT / "manifest.json").read_text())["version"]


def test_js_version_matches_the_manifest() -> None:
    """The version printed by the cards is the integration version."""
    assert f'const HM_VERSION = "{VERSION}";' in JS.read_text()


def test_js_has_no_risky_patterns() -> None:
    """No innerHTML, eval, network requests, external URLs or dynamic imports."""
    source = JS.read_text()
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)  # the header comment mentions innerHTML
    for pattern in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "fetch(",
        "XMLHttpRequest",
        "import(",
        "http://",
        "https://",
        "<script",
    ):
        assert pattern not in code, pattern


async def test_files_are_served_and_cached(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_client
) -> None:
    """The module is served from the integration and is cacheable."""
    await setup_entry(hass, freezer)
    client = await hass_client()
    response = await client.get(f"/home_modes_static/home-modes-cards.js?v={VERSION}")
    assert response.status == 200
    assert response.headers["Content-Type"].startswith(
        ("text/javascript", "application/javascript")
    )
    assert "max-age" in response.headers.get("Cache-Control", "")
    assert await response.text() == JS.read_text()
    assert (await client.get("/home_modes_static/nothing.js")).status == 404


async def test_module_is_registered_with_the_version(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """When the frontend is set up, the module URL carries ?v=<version> (cache-busting)."""
    added: list[tuple[str, str]] = []
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda kind, url: added.append((kind, url)), [])
    await setup_entry(hass, freezer)
    assert added == [("added", f"/home_modes_static/home-modes-cards.js?v={VERSION}")]


async def test_registration_happens_once_across_reloads(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Reloading the entry does not register the module again."""
    added: list[str] = []
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda kind, url: added.append(url), [])
    entry = await setup_entry(hass, freezer)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(added) == 1


async def test_works_without_the_frontend(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without the frontend component the integration still loads (cards are not auto-loaded)."""
    assert DATA_EXTRA_MODULE_URL not in hass.data
    entry = await setup_entry(hass, freezer)
    assert entry.state.name == "LOADED"
