"""Schema tests for the durable PostgreSQL AgentRun queue."""

from __future__ import annotations

from infrastructure.database import models  # noqa: F401
from infrastructure.database.base import Base


def test_queue_metadata_declares_jobs_and_attempts() -> None:
    """Removing either durable queue table must break schema verification."""
    assert "execution_queue_jobs" in Base.metadata.tables
    assert "execution_queue_attempts" in Base.metadata.tables
