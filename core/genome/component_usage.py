"""Bounded component usage history and non-authorizing Genome profiles."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_OBSERVATIONS = 512
_RATE_QUANTUM = Decimal("0.0001")


class ComponentUsageOutcome(StrEnum):
    """Canonical result of one bounded component use."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class _StrictComponentUsageModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ComponentUsageObservation(_StrictComponentUsageModel):
    """Canonical immutable evidence for one component use."""

    event_id: UUID
    agent_id: UUID
    project_id: UUID
    task_id: UUID
    agent_run_id: UUID
    genome_version_id: UUID
    component_manifest_id: UUID
    component_id: UUID
    outcome: ComponentUsageOutcome
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class AgentComponentUsageProfile(_StrictComponentUsageModel):
    """Deterministic historical profile that cannot grant authority."""

    agent_id: UUID
    component_id: UUID
    usage_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    success_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    failure_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    cancelled_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    blocked_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    success_rate: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
    ]
    last_used_at: datetime | None
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_OBSERVATIONS)]
    calculated_at: datetime
    algorithm_version: Literal["genome-component-usage-v1"] = "genome-component-usage-v1"
    may_mutate_trust: Literal[False] = False
    may_grant_authority: Literal[False] = False
    may_mutate_runtime: Literal[False] = False

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("calculated_at must be UTC-aware")
        return value


class AgentComponentUsageProfileCalculator:
    """Aggregate canonical usage evidence without mutating Trust or authority."""

    def calculate(
        self,
        *,
        agent_id: UUID,
        component_id: UUID,
        observations: tuple[ComponentUsageObservation, ...],
        calculated_at: datetime,
    ) -> AgentComponentUsageProfile:
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not ComponentUsageObservation for item in observations):
            raise TypeError("observations must be canonical ComponentUsageObservation values")
        if any(item.agent_id != agent_id for item in observations):
            raise ValueError("observations must belong to the profile agent")
        if any(item.component_id != component_id for item in observations):
            raise ValueError("observations must belong to the profile component")
        if any(item.observed_at > calculated_at for item in observations):
            raise ValueError("component observations cannot follow profile calculation")
        evidence_ids = tuple(item.event_id for item in observations)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("observation event identifiers must be unique")

        usage_count = len(observations)
        success_count = sum(
            item.outcome is ComponentUsageOutcome.SUCCEEDED for item in observations
        )
        return AgentComponentUsageProfile(
            agent_id=agent_id,
            component_id=component_id,
            usage_count=usage_count,
            success_count=success_count,
            failure_count=sum(
                item.outcome is ComponentUsageOutcome.FAILED for item in observations
            ),
            cancelled_count=sum(
                item.outcome is ComponentUsageOutcome.CANCELLED for item in observations
            ),
            blocked_count=sum(
                item.outcome is ComponentUsageOutcome.BLOCKED for item in observations
            ),
            success_rate=_rate(success_count, usage_count),
            last_used_at=max((item.observed_at for item in observations), default=None),
            evidence_ids=evidence_ids,
            calculated_at=calculated_at,
        )


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _RATE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
