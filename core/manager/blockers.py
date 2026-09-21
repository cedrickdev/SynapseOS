"""Deterministic blocker detection for the future AI Manager."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ManagerBlockerCode(StrEnum):
    """Closed observable conditions that can block Manager progress."""

    NO_PROGRESS = "NO_PROGRESS"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    REVIEWER_BACKLOG = "REVIEWER_BACKLOG"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    SECURITY_HOLD = "SECURITY_HOLD"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    NO_ELIGIBLE_AGENT = "NO_ELIGIBLE_AGENT"


class _StrictManagerBlockerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ManagerBlockerSnapshot(_StrictManagerBlockerModel):
    """Bounded observed state used exclusively for deterministic blocker detection."""

    no_progress_cycles: Annotated[int, Field(ge=0, le=1_000)]
    dependency_blocked: bool
    reviewer_queue_depth: Annotated[int, Field(ge=0, le=10_000)]
    provider_available: bool
    security_hold: bool
    approval_pending: bool
    eligible_agent_count: Annotated[int, Field(ge=0, le=100)]


class ManagerBlockerReport(_StrictManagerBlockerModel):
    """Closed ordered blocker output; it does not escalate or mutate workflow state."""

    codes: Annotated[tuple[ManagerBlockerCode, ...], Field(max_length=7)]


class ManagerBlockerDetector:
    """Derive bounded blockers from explicit observed facts only."""

    _NO_PROGRESS_CYCLES = 3
    _REVIEWER_BACKLOG = 10

    def detect(self, snapshot: ManagerBlockerSnapshot) -> ManagerBlockerReport:
        """Return stable blocker codes without inferring or executing a recovery action."""
        if type(snapshot) is not ManagerBlockerSnapshot:
            raise TypeError("snapshot must be a canonical ManagerBlockerSnapshot")
        codes = tuple(
            code
            for condition, code in (
                (
                    snapshot.no_progress_cycles >= self._NO_PROGRESS_CYCLES,
                    ManagerBlockerCode.NO_PROGRESS,
                ),
                (snapshot.dependency_blocked, ManagerBlockerCode.DEPENDENCY_BLOCKED),
                (
                    snapshot.reviewer_queue_depth >= self._REVIEWER_BACKLOG,
                    ManagerBlockerCode.REVIEWER_BACKLOG,
                ),
                (not snapshot.provider_available, ManagerBlockerCode.PROVIDER_UNAVAILABLE),
                (snapshot.security_hold, ManagerBlockerCode.SECURITY_HOLD),
                (snapshot.approval_pending, ManagerBlockerCode.APPROVAL_PENDING),
                (snapshot.eligible_agent_count == 0, ManagerBlockerCode.NO_ELIGIBLE_AGENT),
            )
            if condition
        )
        return ManagerBlockerReport(codes=codes)
