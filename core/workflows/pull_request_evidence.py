"""Persistent validation for Phase 20 workflow evidence bindings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.pull_requests import PullRequestEvidenceBinding
from infrastructure.database.models import PullRequest


def matches_persisted_pull_request(
    session: Session,
    *,
    task_id: UUID,
    correlation_id: UUID,
    evidence: PullRequestEvidenceBinding | None,
) -> bool:
    """Return whether an optional binding exactly matches one immutable PR."""
    if evidence is None:
        return True
    pull_request_id = session.scalar(
        select(PullRequest.id).where(
            PullRequest.task_id == task_id,
            PullRequest.correlation_id == correlation_id,
            PullRequest.head_sha == evidence.head_sha,
            PullRequest.preparation_checksum == evidence.preparation_checksum,
        )
    )
    return pull_request_id is not None
