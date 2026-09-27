"""Fail-closed authorization policy for internal human control commands."""

from __future__ import annotations

from core.control_api.errors import ControlError, ControlErrorCode
from core.control_api.types import ControlPrincipal, ControlRole


def require_any_role(principal: ControlPrincipal, *roles: ControlRole) -> None:
    if type(principal) is not ControlPrincipal or not set(principal.roles).intersection(roles):
        raise ControlError(ControlErrorCode.FORBIDDEN)
