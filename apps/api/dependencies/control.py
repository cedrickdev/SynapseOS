"""Trusted service-to-service principal construction for control commands."""

from __future__ import annotations

from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import record_authentication_outcome
from apps.api.dependencies.dashboard import require_dashboard_access
from core.auth import OIDCClaims, OIDCVerificationError
from core.control_api import ControlPrincipal, ControlRole
from core.enums import AuditResult
from infrastructure.auth import RBACAuthorizationError, SQLAlchemyRBACResolver
from infrastructure.control_api.service import TransactionalQueue
from infrastructure.database.session import get_session

_BEARER = HTTPBearer(auto_error=False)


class _Verifier(Protocol):
    async def verify(self, token: str) -> OIDCClaims: ...


async def get_control_principal(
    _access: Annotated[None, Depends(require_dashboard_access)],
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    actor_id: Annotated[
        str | None,
        Header(alias="X-SynapseOS-Actor-Id", min_length=1, max_length=128),
    ] = None,
    company_id: Annotated[
        str, Header(alias="X-SynapseOS-Company-Id", min_length=1, max_length=128)
    ] = "",
    roles: Annotated[
        str | None,
        Header(alias="X-SynapseOS-Control-Roles", min_length=1, max_length=128),
    ] = None,
) -> ControlPrincipal:
    """Build authority from OIDC+RBAC, or trusted internal headers when OIDC is absent."""
    verifier = cast(_Verifier | None, getattr(request.app.state, "oidc_verifier", None))
    authorization_supplied = "authorization" in request.headers
    if verifier is not None and authorization_supplied:
        try:
            if credentials is None or credentials.scheme.casefold() != "bearer" or not company_id:
                raise OIDCVerificationError
            claims = await verifier.verify(credentials.credentials)
            raw_project_id = request.path_params.get("project_id")
            project_id = UUID(str(raw_project_id)) if raw_project_id is not None else None
        except (OIDCVerificationError, TypeError, ValueError):
            record_authentication_outcome(
                session,
                event_type="AUTHENTICATION_FAILED",
                result=AuditResult.DENIED,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "AUTHENTICATION_FAILED",
                    "message": "Authentication failed.",
                },
            ) from None
        try:
            principal = SQLAlchemyRBACResolver(session).resolve(
                claims,
                company_slug=company_id,
                project_id=project_id,
            )
        except RBACAuthorizationError:
            record_authentication_outcome(
                session,
                event_type="AUTHORIZATION_DENIED",
                result=AuditResult.DENIED,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "AUTHORIZATION_DENIED",
                    "message": "Access denied.",
                },
            ) from None
        record_authentication_outcome(
            session,
            event_type="AUTHENTICATION_SUCCEEDED",
            result=AuditResult.SUCCEEDED,
            actor_id=principal.actor_id,
            company_id=str(principal.company_id),
        )
        return principal
    try:
        if actor_id is None or roles is None or not company_id:
            raise ValueError
        parsed = tuple(ControlRole(item.strip()) for item in roles.split(",") if item.strip())
        return ControlPrincipal(actor_id=actor_id, company_id=UUID(company_id), roles=parsed)
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
