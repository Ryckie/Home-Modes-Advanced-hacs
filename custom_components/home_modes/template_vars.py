"""Template variables shared by actions and notifications.

``from`` is a reserved word in Jinja, so it is not available. Logic should use the role ids
(``from_role``/``to_role``, aliases ``from_mode``/``to_mode``); names are for display only.
"""

from __future__ import annotations

from typing import Any

from .coordinator import HomeModesCoordinator


def role_name(coordinator: HomeModesCoordinator, role_id: str | None) -> str:
    """Return the display name of a role ('' for none, the id if the role is gone)."""
    if role_id is None:
        return ""
    role = coordinator.role(role_id)
    return role.name if role else role_id


def role_variables(
    coordinator: HomeModesCoordinator, from_role: str | None, to_role: str | None
) -> dict[str, Any]:
    """Return the from/to variables: ids in from_role/to_role/from_mode/to_mode, names in *_name."""
    return {
        "from_role": from_role or "",
        "to_role": to_role or "",
        "from_mode": from_role or "",
        "to_mode": to_role or "",
        "from_name": role_name(coordinator, from_role),
        "to_name": role_name(coordinator, to_role),
    }
