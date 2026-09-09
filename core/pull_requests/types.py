"""Immutable Phase 20 pull-request and merge-gate contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PullRequestStatus(StrEnum):
    """Internal pull-request lifecycle states owned by SynapseOS."""

    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    READY_TO_MERGE = "READY_TO_MERGE"
    CLOSED = "CLOSED"


class PullRequestRiskSeverity(StrEnum):
    """Allowlisted risk severities persisted in pull-request summaries."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PullRequestReviewDecision(StrEnum):
    """Independent reviewer decisions."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class ApprovalKind(StrEnum):
    """Required independent approval roles."""

    REVIEWER = "REVIEWER"
    QA = "QA"
    SECURITY = "SECURITY"


class ApprovalDecision(StrEnum):
    """Terminal approval evidence decisions."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class MergeGateDecision(StrEnum):
    """Fail-closed merge-gate outcome."""

    PASS = "PASS"
    BLOCK = "BLOCK"


class MergeGateReason(StrEnum):
    """Stable reasons explaining a blocked merge gate."""

    TASK_MISMATCH = "TASK_MISMATCH"
    PROJECT_TASK_MISMATCH = "PROJECT_TASK_MISMATCH"
    AUTHOR_TASK_MISMATCH = "AUTHOR_TASK_MISMATCH"
    AUTHOR_IS_REVIEWER = "AUTHOR_IS_REVIEWER"
    REVIEWER_ROLE_MISMATCH = "REVIEWER_ROLE_MISMATCH"
    APPROVER_IDENTITY_CONFLICT = "APPROVER_IDENTITY_CONFLICT"
    APPROVER_ROLE_MISMATCH = "APPROVER_ROLE_MISMATCH"
    REVIEW_NOT_APPROVED = "REVIEW_NOT_APPROVED"
    REVIEWER_APPROVAL_MISSING = "REVIEWER_APPROVAL_MISSING"
    QA_NOT_PASSED = "QA_NOT_PASSED"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    TESTS_NOT_PASSED = "TESTS_NOT_PASSED"
    BRANCH_NOT_MERGEABLE = "BRANCH_NOT_MERGEABLE"
    STALE_EVIDENCE = "STALE_EVIDENCE"


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PullRequestEvidenceBinding(_ImmutableModel):
    """Exact immutable Git state attached to downstream workflow evidence."""

    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    preparation_checksum: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PullRequestCandidate(_ImmutableModel):
    pull_request_id: UUID
    project_id: UUID
    task_id: UUID
    author_agent_id: UUID
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    correlation_id: UUID


class PullRequestReviewEvidence(_ImmutableModel):
    reviewer_agent_id: UUID
    reviewer_role: Annotated[str, Field(min_length=1, max_length=64)]
    decision: PullRequestReviewDecision
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    correlation_id: UUID


class ApprovalEvidence(_ImmutableModel):
    kind: ApprovalKind
    approver_agent_id: UUID
    approver_role: Annotated[str, Field(min_length=1, max_length=64)]
    decision: ApprovalDecision
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
    correlation_id: UUID


class PullRequestTestEvidence(_ImmutableModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    passed: bool
    truncated: bool
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]


class PullRequestRisk(_ImmutableModel):
    severity: PullRequestRiskSeverity
    summary: Annotated[str, Field(min_length=1, max_length=1_024)]

    @field_validator("summary")
    @classmethod
    def require_trimmed_summary(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("risk summary is invalid")
        return value


class MergeGateRequest(_ImmutableModel):
    expected_task_id: UUID
    candidate: PullRequestCandidate
    review: PullRequestReviewEvidence | None
    approvals: Annotated[tuple[ApprovalEvidence, ...], Field(max_length=3)]
    tests: Annotated[tuple[PullRequestTestEvidence, ...], Field(max_length=32)]
    branch_mergeable: bool

    @field_validator("approvals", "tests", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_approval_kinds(self) -> Self:
        if len({approval.kind for approval in self.approvals}) != len(self.approvals):
            raise ValueError("approval kinds must be unique")
        return self


class MergeGateResult(_ImmutableModel):
    decision: MergeGateDecision
    reasons: Annotated[tuple[MergeGateReason, ...], Field(max_length=16)] = ()

    @model_validator(mode="after")
    def require_consistent_result(self) -> Self:
        if self.decision is MergeGateDecision.PASS and self.reasons:
            raise ValueError("passing gate cannot contain reasons")
        if self.decision is MergeGateDecision.BLOCK and not self.reasons:
            raise ValueError("blocked gate requires reasons")
        return self
