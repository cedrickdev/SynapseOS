"""Health check endpoint for the Platform API."""

from __future__ import annotations

from typing import Protocol, cast

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(tags=["health"])


class _DatabaseReadiness(Protocol):
    async def check_database_readiness(self) -> bool: ...


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns HTTP 200 when the API process is up.

    Intentionally does not touch the database: this is a liveness signal, not a
    readiness/dependency check.
    """
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request) -> dict[str, str]:
    """Return ready only when production-owned PostgreSQL is reachable."""
    resources = getattr(request.app.state, "production_resources", None)
    checker = getattr(resources, "check_database_readiness", None)
    if not callable(checker):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service is not ready",
        )
    try:
        ready = await cast(_DatabaseReadiness, resources).check_database_readiness()
    except Exception:
        ready = False
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service is not ready",
        )
    return {"status": "ready"}
