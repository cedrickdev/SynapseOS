"""Trusted service-to-service principal construction for control commands."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request, status

from apps.api.dependencies.dashboard import require_dashboard_access
from core.control_api import ControlPrincipal, ControlRole
from infrastructure.control_api.service import TransactionalQueue


def get_control_principal(
    _access: Annotated[None, Depends(require_dashboard_access)],
    actor_id: Annotated[str, Header(alias="X-SynapseOS-Actor-Id", min_length=1, max_length=128)],
    company_id: Annotated[
        str, Header(alias="X-SynapseOS-Company-Id", min_length=1, max_length=128)
    ],
    roles: Annotated[str, Header(alias="X-SynapseOS-Control-Roles", min_length=1, max_length=128)],
) -> ControlPrincipal:
    """Build a bounded human principal after private service authentication."""
    try:
        parsed = tuple(ControlRole(item.strip()) for item in roles.split(",") if item.strip())
        return ControlPrincipal(actor_id=actor_id, company_id=company_id, roles=parsed)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CONTROL_FORBIDDEN", "message": "Command denied."},
        ) from None


def get_control_queue(request: Request) -> TransactionalQueue:
    """Resolve only the high-level queue from the production composition root."""
    resources = getattr(request.app.state, "production_resources", None)
    if resources is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONTROL_UNAVAILABLE", "message": "Control service unavailable."},
        )
    try:
        return cast(TransactionalQueue, resources.execution_queue)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONTROL_UNAVAILABLE", "message": "Control service unavailable."},
        ) from None
