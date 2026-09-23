"""Versioned, non-authorizing Agent Genome cost and efficiency profiles."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_OBSERVATIONS = 512
_SCALE = Decimal("0.00000001")
_ALGORITHM_VERSION = "genome-cost-efficiency-profile-v1"


class CostEfficiencyProfileState(StrEnum):
    """Whether sufficient attributed usage evidence exists for a profile."""

    COLD_START = "COLD_START"
    ESTABLISHED = "ESTABLISHED"


class _StrictCostEfficiencyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CostEfficiencyObservation(_StrictCostEfficiencyModel):
    """One bounded run-attributed resource-use observation."""

    evidence_id: UUID
    run_id: UUID
    agent_id: UUID
    total_tokens: Annotated[int, Field(ge=0, le=10_000_000)]
    duration_ms: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=20, decimal_places=8)]
    provider_cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=20, decimal_places=8)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class AgentCostEfficiencyProfile(_StrictCostEfficiencyModel):
    """Historical resource-use profile that never grants authority or selects a route."""

    agent_id: UUID
    genome_version_id: UUID
    profile_version: Annotated[int, Field(ge=1, le=1_000_000)]
    state: CostEfficiencyProfileState
    median_total_tokens: Decimal | None
    median_duration_ms: Decimal | None
    median_provider_cost: Decimal | None
    sample_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_OBSERVATIONS)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    created_at: datetime
    may_influence_authority: Literal[False] = False
    may_select_provider_or_route: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.sample_count != len(self.evidence_ids):
            raise ValueError("sample_count must match evidence identifiers")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("profile evidence identifiers must be unique")
        metrics = (
            self.median_total_tokens,
            self.median_duration_ms,
            self.median_provider_cost,
        )
        cold = self.state is CostEfficiencyProfileState.COLD_START
        if cold != (self.sample_count == 0):
            raise ValueError("cold-start state must match an empty sample")
        if cold != all(value is None for value in metrics):
            raise ValueError("cold-start metrics must be absent")
        if not cold and any(value is None for value in metrics):
            raise ValueError("established profiles require all efficiency metrics")
        return self


class AgentCostEfficiencyProfileBuilder:
    """Build reproducible historical medians without cost routing or authority changes."""

    def build(
        self,
        *,
        agent_id: UUID,
        genome_version_id: UUID,
        profile_version: int,
        observations: tuple[CostEfficiencyObservation, ...],
        created_at: datetime,
    ) -> AgentCostEfficiencyProfile:
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not CostEfficiencyObservation for item in observations):
            raise TypeError("observations must be canonical CostEfficiencyObservation values")
        if any(item.agent_id != agent_id for item in observations):
            raise ValueError("observations must belong to the profile agent")
        evidence_ids = tuple(item.evidence_id for item in observations)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("observation evidence identifiers must be unique")
        if len({item.run_id for item in observations}) != len(observations):
            raise ValueError("cost-efficiency observations must represent unique runs")
        if any(item.observed_at > created_at for item in observations):
            raise ValueError("cost-efficiency observations cannot follow profile creation")

        return AgentCostEfficiencyProfile(
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            profile_version=profile_version,
            state=(
                CostEfficiencyProfileState.ESTABLISHED
                if observations
                else CostEfficiencyProfileState.COLD_START
            ),
            median_total_tokens=(
                _median(tuple(Decimal(item.total_tokens) for item in observations))
                if observations
                else None
            ),
            median_duration_ms=(
                _median(tuple(item.duration_ms for item in observations)) if observations else None
            ),
            median_provider_cost=(
                _median(tuple(item.provider_cost for item in observations))
                if observations
                else None
            ),
            sample_count=len(observations),
            evidence_ids=evidence_ids,
            algorithm_version=_ALGORITHM_VERSION,
            created_at=created_at,
        )


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    value = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / Decimal("2")
    )
    return value.quantize(_SCALE, rounding=ROUND_HALF_UP)
