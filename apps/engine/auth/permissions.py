"""Whether a role may run an action type, after the org's overrides."""

from __future__ import annotations

from collections.abc import Mapping

from engine.core.config import Permissions
from engine.core.types import ActionType, PermissionDenied, Role


def allowed(
    permissions: Permissions,
    role: Role,
    action_type: ActionType,
    overrides: Mapping[Role, frozenset[ActionType]] | None = None,
) -> bool:
    """True when the role may run the action type. An org override replaces the default."""
    granted = (overrides or {}).get(role, permissions.allowed(role))
    return action_type in granted


def require(
    permissions: Permissions,
    role: Role,
    action_type: ActionType,
    action: str,
    overrides: Mapping[Role, frozenset[ActionType]] | None = None,
) -> None:
    """Raise PermissionDenied unless the role may run the action type."""
    if not allowed(permissions, role, action_type, overrides):
        raise PermissionDenied(f"a {role.value} may not run {action} ({action_type.value})")
