"""Health check endpoint for the Platform API."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns HTTP 200 when the API process is up.

    Intentionally does not touch the database: this is a liveness signal, not a
    readiness/dependency check.
    """
    return {"status": "ok"}
