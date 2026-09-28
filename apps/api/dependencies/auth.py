"""Shared OIDC authentication, RBAC resolution, and sanitized audit helpers."""

from __future__ import annotations

from typing import Annotated, Protocol, cast

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.dependencies.dashboard import require_dashboard_access
from core.auth import OIDCClaims, OIDCVerificationError
from core.control_api import ControlPrincipal
from core.enums import AuditActorType, AuditResult
from infrastructure.auth import RBACAuthorizationError, SQLAlchemyRBACResolver
from infrastructure.database.models import AuditEvent
from infrastructure.database.session import get_session

_BEARER = HTTPBearer(auto_error=False)


class _Verifier(Protocol):
    async def verify(self, token: str) -> OIDCClaims: ...


def record_authentication_outcome(
    session: Session,
    *,
    event_type: str,
    result: AuditResult,
    actor_id: str | None = None,
    company_id: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_type=AuditActorType.HUMAN if actor_id is not None else None,
            actor_id=actor_id,
            event_type=event_type,
            action="authenticate",
            resource_type="COMPANY" if company_id is not None else None,
            resource_id=company_id,
            result=result,
            data={},
        )
    )
    session.commit()


async def get_dashboard_principal(
    _access: Annotated[None, Depends(require_dashboard_access)],
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    company_id: Annotated[
        str | None, Header(alias="X-SynapseOS-Company-Id", min_length=1, max_length=128)
    ] = None,
) -> ControlPrincipal | None:
    """Authenticate a human dashboard request or preserve trusted internal compatibility."""
    verifier = cast(_Verifier | None, getattr(request.app.state, "oidc_verifier", None))
    authorization_supplied = "authorization" in request.headers
    if verifier is None or not authorization_supplied:
        return None
    try:
        if credentials is None or credentials.scheme.casefold() != "bearer" or not company_id:
            raise OIDCVerificationError()
        claims = await verifier.verify(credentials.credentials)
    except OIDCVerificationError:
        record_authentication_outcome(
            session,
            event_type="AUTHENTICATION_FAILED",
            result=AuditResult.DENIED,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_FAILED", "message": "Authentication failed."},
        ) from None
    try:
        principal = SQLAlchemyRBACResolver(session).resolve(claims, company_slug=company_id)
    except RBACAuthorizationError:
        record_authentication_outcome(
            session,
            event_type="AUTHORIZATION_DENIED",
            result=AuditResult.DENIED,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTHORIZATION_DENIED", "message": "Access denied."},
        ) from None
    record_authentication_outcome(
        session,
        event_type="AUTHENTICATION_SUCCEEDED",
        result=AuditResult.SUCCEEDED,
        actor_id=principal.actor_id,
        company_id=str(principal.company_id),
    )
    return principal
