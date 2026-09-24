"""Bounded coordination of independent read-only Sentinel agents."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.sentinel import SentinelRiskSignal as SentinelRiskSignal


class _StrictSentinelModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class SentinelCandidate(_StrictSentinelModel):
    agent_id: UUID
    scratchpad_ref: Annotated[str, Field(min_length=1, max_length=512)]
    read_only: bool
    can_manage_permissions: bool
    independently_auditable: bool
    timeout_seconds: Annotated[int, Field(ge=1, le=3_600)]
    max_tool_calls: Annotated[int, Field(ge=1, le=128)]
    cost_limit: Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("1000"))]


class SentinelCoordinationRequest(_StrictSentinelModel):
    target_agent_id: UUID
    target_scratchpad_ref: Annotated[str, Field(min_length=1, max_length=512)]
    evidence_references: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    requested_signals: Annotated[tuple[SentinelRiskSignal, ...], Field(min_length=1, max_length=7)]
    candidates: Annotated[tuple[SentinelCandidate, ...], Field(max_length=256)]
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
    def validate_request(self) -> Self:
        groups: tuple[tuple[object, ...], ...] = (
            self.evidence_references,
            self.requested_signals,
            tuple(item.agent_id for item in self.candidates),
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("sentinel coordination values must be unique")
        if any(
            not value
            or len(value) > 512
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
            for value in (self.target_scratchpad_ref, *self.evidence_references)
        ):
            raise ValueError("sentinel references must be bounded and content-safe")
        return self


class SentinelCoordinationPlan(_StrictSentinelModel):
    target_agent_id: UUID
    sentinel_agent_id: UUID | None
    evidence_references: Annotated[tuple[str, ...], Field(max_length=256)]
    requested_signals: Annotated[tuple[SentinelRiskSignal, ...], Field(max_length=7)]
    timeout_seconds: int | None
    max_tool_calls: int | None
    cost_limit: Decimal | None
    coordinated_at: datetime
    may_suspend: Literal[False] = False
    may_grant_permissions: Literal[False] = False
    may_revoke_permissions: Literal[False] = False
    may_execute: Literal[False] = False


class ManagerSentinelCoordinator:
    """Choose an independent bounded observer; never act on its behalf."""

    def coordinate(self, request: SentinelCoordinationRequest) -> SentinelCoordinationPlan:
        if type(request) is not SentinelCoordinationRequest:
            raise TypeError("request must be a canonical SentinelCoordinationRequest")
        eligible = [
            item
            for item in request.candidates
            if item.agent_id != request.target_agent_id
            and item.scratchpad_ref != request.target_scratchpad_ref
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
        return SentinelCoordinationPlan(
            target_agent_id=request.target_agent_id,
            sentinel_agent_id=selected.agent_id if selected else None,
            evidence_references=request.evidence_references,
            requested_signals=request.requested_signals,
            timeout_seconds=selected.timeout_seconds if selected else None,
            max_tool_calls=selected.max_tool_calls if selected else None,
            cost_limit=selected.cost_limit if selected else None,
            coordinated_at=request.coordinated_at,
        )
