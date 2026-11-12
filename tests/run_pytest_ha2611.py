"""Run pytest on Home Assistant 2026.11.x (best-effort CI target).

pytest-homeassistant-custom-component 0.13.375 targets Home Assistant 2026.10.4.
On 2026.11.x it needs two workarounds that must run before the plugin loads, which is
why they cannot live in conftest.py:

1. ``import homeassistant`` before ``httpx`` (Home Assistant checks the import order).
2. ``homeassistant.components.logger._clear_logger_overwrites`` no longer exists; the
   plugin still calls it, so a no-op replacement is installed.

Remove this file when the plugin supports 2026.11. Nothing here is shipped in
custom_components/.
"""

from __future__ import annotations

import sys

import homeassistant  # noqa: F401  (must stay the first import)
import homeassistant.components.logger as ha_logger
import pytest

ha_logger._clear_logger_overwrites = lambda hass: None  # type: ignore[attr-defined]

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
