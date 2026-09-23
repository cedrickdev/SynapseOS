"""Independent peer-audit planning for Sentinel submissions."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.sentinels import (
    SentinelCandidate,
    SentinelCoordinationPlan,
    SentinelRiskSignal,
)


class _StrictPeerAuditModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class SentinelAuditSubmission(_StrictPeerAuditModel):
    target_agent_id: UUID
    sentinel_agent_id: UUID
    sentinel_scratchpad_ref: Annotated[str, Field(min_length=1, max_length=512)]
    evidence_references: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    signals: Annotated[tuple[SentinelRiskSignal, ...], Field(min_length=1, max_length=7)]
    audit_reference: Annotated[str, Field(min_length=1, max_length=512)]
    submitted_at: datetime

    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("submitted_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_submission(self) -> Self:
        if self.target_agent_id == self.sentinel_agent_id:
            raise ValueError("Sentinel and target identities must differ")
        groups: tuple[tuple[object, ...], ...] = (self.evidence_references, self.signals)
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("Sentinel audit evidence and signals must be unique")
        if any(
            not value
            or len(value) > 512
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
            for value in (
                self.sentinel_scratchpad_ref,
                self.audit_reference,
                *self.evidence_references,
            )
        ):
            raise ValueError("peer-audit references must be bounded and content-safe")
        return self


class PeerAuditRequest(_StrictPeerAuditModel):
    primary_plan: SentinelCoordinationPlan
    primary_submission: SentinelAuditSubmission
    target_scratchpad_ref: Annotated[str, Field(min_length=1, max_length=512)]
    peer_candidates: Annotated[tuple[SentinelCandidate, ...], Field(max_length=256)]
    timeout_limit_seconds: Annotated[int, Field(ge=1, le=3_600)]
    tool_call_limit: Annotated[int, Field(ge=1, le=128)]
    cost_limit: Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("1000"))]
    coordinated_at: datetime

    @field_validator("coordinated_at")
    @classmethod
    def validate_coordinated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("coordinated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_candidates(self) -> Self:
        identifiers = tuple(item.agent_id for item in self.peer_candidates)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("peer candidates must be unique")
        return self


class PeerAuditPlan(_StrictPeerAuditModel):
    target_agent_id: UUID
    primary_sentinel_agent_id: UUID
    peer_auditor_agent_id: UUID | None
    audit_reference: str
    evidence_references: Annotated[tuple[str, ...], Field(max_length=256)]
    signals: Annotated[tuple[SentinelRiskSignal, ...], Field(max_length=7)]
    timeout_seconds: int | None
    max_tool_calls: int | None
    cost_limit: Decimal | None
    coordinated_at: datetime
    may_accept_signal: Literal[False] = False
    may_mutate_trust: Literal[False] = False
    may_change_autonomy: Literal[False] = False
    may_execute: Literal[False] = False


class IndependentPeerAuditCoordinator:
    """Prepare an independent review of one canonical Sentinel submission."""

    def coordinate(self, request: PeerAuditRequest) -> PeerAuditPlan:
        if type(request) is not PeerAuditRequest:
            raise TypeError("request must be a canonical PeerAuditRequest")
        plan = request.primary_plan
        submission = request.primary_submission
        if plan.sentinel_agent_id is None:
            raise ValueError("primary coordination plan has no Sentinel")
        if (
            submission.target_agent_id != plan.target_agent_id
            or submission.sentinel_agent_id != plan.sentinel_agent_id
            or submission.evidence_references != plan.evidence_references
            or not set(submission.signals).issubset(plan.requested_signals)
        ):
            raise ValueError("primary submission must match the coordination plan")
        if (
            submission.submitted_at < plan.coordinated_at
            or submission.submitted_at > request.coordinated_at
        ):
            raise ValueError("peer-audit chronology is invalid")

        excluded_identities = {plan.target_agent_id, plan.sentinel_agent_id}
        excluded_scratchpads = {
            request.target_scratchpad_ref,
            submission.sentinel_scratchpad_ref,
        }
        eligible = [
            item
            for item in request.peer_candidates
            if item.agent_id not in excluded_identities
            and item.scratchpad_ref not in excluded_scratchpads
            and item.read_only
            and not item.can_manage_permissions
            and item.independently_auditable
            and item.timeout_seconds <= request.timeout_limit_seconds
            and item.max_tool_calls <= request.tool_call_limit
            and item.cost_limit <= request.cost_limit
        ]
        eligible.sort(
            key=lambda item: (
                item.cost_limit,
                item.timeout_seconds,
                item.max_tool_calls,
                item.agent_id.hex,
            )
        )
        selected = eligible[0] if eligible else None
        return PeerAuditPlan(
            target_agent_id=plan.target_agent_id,
            primary_sentinel_agent_id=plan.sentinel_agent_id,
            peer_auditor_agent_id=selected.agent_id if selected else None,
            audit_reference=submission.audit_reference,
            evidence_references=submission.evidence_references,
            signals=submission.signals,
            timeout_seconds=selected.timeout_seconds if selected else None,
            max_tool_calls=selected.max_tool_calls if selected else None,
            cost_limit=selected.cost_limit if selected else None,
            coordinated_at=request.coordinated_at,
        )
