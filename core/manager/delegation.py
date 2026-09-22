"""Bounded, non-authorizing AI Manager delegation-chain planning."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.trust import DelegationIntegrityDisposition, DelegationIntegrityResult

_IDENTIFIER = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class DelegationPlanDisposition(StrEnum):
    PROPOSE = "PROPOSE"
    REJECT = "REJECT"


class DelegationPlanReason(StrEnum):
    PARENT_INTEGRITY_VIOLATION = "PARENT_INTEGRITY_VIOLATION"
    CHAIN_LIMIT_REACHED = "CHAIN_LIMIT_REACHED"
    SCOPE_EXCEEDS_PARENT = "SCOPE_EXCEEDS_PARENT"
    CAPABILITY_EXCEEDS_PARENT = "CAPABILITY_EXCEEDS_PARENT"
    INVALID_LIFETIME = "INVALID_LIFETIME"
    PARENT_INACTIVE = "PARENT_INACTIVE"


class _StrictDelegationPlanModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class DelegationPlanRequest(_StrictDelegationPlanModel):
    parent_integrity: DelegationIntegrityResult
    proposed_delegation_id: UUID
    delegate_agent_id: UUID
    requested_scopes: Annotated[tuple[_IDENTIFIER, ...], Field(min_length=1, max_length=64)]
    requested_capabilities: Annotated[tuple[_IDENTIFIER, ...], Field(min_length=1, max_length=64)]
    expires_at: datetime
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]
    planned_at: datetime

    @field_validator("expires_at", "planned_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("delegation plan timestamps must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_unique_members(self) -> Self:
        if len(self.requested_scopes) != len(set(self.requested_scopes)):
            raise ValueError("requested_scopes must be unique")
        if len(self.requested_capabilities) != len(set(self.requested_capabilities)):
            raise ValueError("requested_capabilities must be unique")
        if self.parent_integrity.evaluated_at > self.planned_at:
            raise ValueError("parent integrity cannot follow delegation planning")
        return self


class DelegationGrantDraft(_StrictDelegationPlanModel):
    delegation_id: UUID
    principal_id: _IDENTIFIER
    delegator_agent_id: UUID
    delegate_agent_id: UUID
    project_id: UUID
    task_id: UUID
    allowed_scopes: tuple[_IDENTIFIER, ...]
    allowed_capabilities: tuple[_IDENTIFIER, ...]
    issued_at: datetime
    expires_at: datetime
    parent_delegation_id: UUID
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]


class ManagerDelegationPlanResult(_StrictDelegationPlanModel):
    request: DelegationPlanRequest
    disposition: DelegationPlanDisposition
    reasons: Annotated[tuple[DelegationPlanReason, ...], Field(max_length=6)]
    draft: DelegationGrantDraft | None
    resulting_chain_depth: Annotated[int, Field(ge=1, le=16)]
    may_issue_delegation: Literal[False] = False
    may_mutate_permissions: Literal[False] = False
    may_execute: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        rejected = bool(self.reasons)
        if (self.disposition is DelegationPlanDisposition.REJECT) != rejected:
            raise ValueError("delegation disposition must match reasons")
        if (self.draft is None) != rejected:
            raise ValueError("only accepted delegation plans contain a draft")
        return self


class ManagerDelegationChainPlanner:
    """Plan one bounded child delegation without issuing authority."""

    def plan(self, request: DelegationPlanRequest) -> ManagerDelegationPlanResult:
        if type(request) is not DelegationPlanRequest:
            raise TypeError("request must be a canonical DelegationPlanRequest")
        integrity = request.parent_integrity
        parent = integrity.chain[-1]
        depth = len(integrity.chain) + 1
        reasons = tuple(
            reason
            for condition, reason in (
                (
                    integrity.disposition is DelegationIntegrityDisposition.INTEGRITY_VIOLATION,
                    DelegationPlanReason.PARENT_INTEGRITY_VIOLATION,
                ),
                (depth > 16, DelegationPlanReason.CHAIN_LIMIT_REACHED),
                (
                    not set(request.requested_scopes).issubset(parent.allowed_scopes),
                    DelegationPlanReason.SCOPE_EXCEEDS_PARENT,
                ),
                (
                    not set(request.requested_capabilities).issubset(parent.allowed_capabilities),
                    DelegationPlanReason.CAPABILITY_EXCEEDS_PARENT,
                ),
                (
                    request.expires_at <= request.planned_at,
                    DelegationPlanReason.INVALID_LIFETIME,
                ),
                (
                    parent.expires_at <= request.planned_at
                    or request.expires_at > parent.expires_at
                    or (parent.revoked_at is not None and parent.revoked_at <= request.planned_at),
                    DelegationPlanReason.PARENT_INACTIVE,
                ),
            )
            if condition
        )
        draft = None
        if not reasons:
            draft = DelegationGrantDraft(
                delegation_id=request.proposed_delegation_id,
                principal_id=parent.principal_id,
                delegator_agent_id=parent.delegate_agent_id,
                delegate_agent_id=request.delegate_agent_id,
                project_id=parent.project_id,
                task_id=parent.task_id,
                allowed_scopes=request.requested_scopes,
                allowed_capabilities=request.requested_capabilities,
                issued_at=request.planned_at,
                expires_at=request.expires_at,
                parent_delegation_id=parent.delegation_id,
                evidence_reference=request.evidence_reference,
            )
        return ManagerDelegationPlanResult(
            request=request,
            disposition=(
                DelegationPlanDisposition.REJECT if reasons else DelegationPlanDisposition.PROPOSE
            ),
            reasons=reasons,
            draft=draft,
            resulting_chain_depth=min(depth, 16),
        )
