"""Private service authentication for dashboard read contracts."""

from __future__ import annotations

from hmac import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, Request, status


def require_dashboard_access(
    request: Request,
    service_token: Annotated[
        str | None,
        Header(alias="X-SynapseOS-Service-Token", include_in_schema=False),
    ] = None,
) -> None:
    """Require the server-held dashboard token without disclosing configuration."""
    expected = getattr(request.app.state, "dashboard_service_token", None)
    if not isinstance(expected, str) or not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard API access is not configured.",
        )
    if service_token is None or not compare_digest(service_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dashboard API access is unauthorized.",
        )
