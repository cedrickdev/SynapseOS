"""Persistence port used by the provider-neutral closure workflow."""

from __future__ import annotations

import uuid
from typing import Protocol

from core.closure.types import (
    AgentContributionSummary,
    CelebrationMessage,
    ClosureMetrics,
)


class ClosureSnapshot:
    """Read-only project facts collected before any closure mutation."""

    __slots__ = ("metrics", "contributions")

    def __init__(
        self,
        metrics: ClosureMetrics,
        contributions: tuple[AgentContributionSummary, ...],
    ) -> None:
        self.metrics = metrics
        self.contributions = contributions


class ClosurePersistenceResult:
    """Identifiers produced by the persistence boundary."""

    __slots__ = ("released_agent_ids", "audit_event_ids")

    def __init__(
        self,
        released_agent_ids: tuple[uuid.UUID, ...],
        audit_event_ids: tuple[uuid.UUID, ...],
    ) -> None:
        self.released_agent_ids = released_agent_ids
        self.audit_event_ids = audit_event_ids


class ProjectClosureStore(Protocol):
    """Store required by the closure workflow."""

    def collect(self, project_id: uuid.UUID) -> ClosureSnapshot:
        """Collect deterministic facts without mutating persistence."""

    def close(
        self,
        project_id: uuid.UUID,
        *,
        correlation_id: uuid.UUID,
        metrics: ClosureMetrics,
        retrospective: str,
        celebrations: tuple[CelebrationMessage, ...],
    ) -> ClosurePersistenceResult:
        """Apply the archive/release transition in the caller-owned transaction."""
