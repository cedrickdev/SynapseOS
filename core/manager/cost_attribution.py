"""Deterministic, non-authorizing cost attribution for one agent run."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_EVIDENCE = 512
_MONEY_SCALE = Decimal("0.00000001")


class CostAttributionSource(StrEnum):
    """Closed cost buckets that explain why a run incurred cost."""

    PROVIDER_CALL = "PROVIDER_CALL"
    REVIEWER_CALL = "REVIEWER_CALL"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    RETRY = "RETRY"


class _StrictCostAttributionModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AttributableCostEvidence(_StrictCostAttributionModel):
    """One immutable cost measurement bound to an exact governed run."""

    evidence_id: UUID
    project_id: UUID
    task_id: UUID
    run_id: UUID
    agent_id: UUID
    genome_version_id: UUID
    source: CostAttributionSource
    provider_reference: Annotated[str | None, Field(min_length=1, max_length=256)] = None
    input_tokens: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    output_tokens: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=20, decimal_places=8)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value

    @field_validator("provider_reference")
    @classmethod
    def validate_provider_reference(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("provider_reference must be bounded and content-safe")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        provider_source = self.source in {
            CostAttributionSource.PROVIDER_CALL,
            CostAttributionSource.REVIEWER_CALL,
        }
        if provider_source and self.provider_reference is None:
            raise ValueError("provider and reviewer calls require a provider reference")
        if self.source is CostAttributionSource.TOOL_EXECUTION and (
            self.input_tokens != 0 or self.output_tokens != 0
        ):
            raise ValueError("tool execution evidence cannot report model tokens")
        return self


class AgentCostAttributionRequest(_StrictCostAttributionModel):
    """Bounded evidence set for one project, task, agent, and run."""

    project_id: UUID
    task_id: UUID
    run_id: UUID
    agent_id: UUID
    genome_version_id: UUID
    evidence: Annotated[tuple[AttributableCostEvidence, ...], Field(max_length=_MAX_EVIDENCE)]
    calculated_at: datetime

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("calculated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def require_unique_evidence(self) -> Self:
        identifiers = tuple(item.evidence_id for item in self.evidence)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("cost attribution evidence identifiers must be unique")
        return self


class AgentCostAttribution(_StrictCostAttributionModel):
    """Explainable run cost that cannot spend, assign, or change a budget."""

    project_id: UUID
    task_id: UUID
    run_id: UUID
    agent_id: UUID
    genome_version_id: UUID
    provider_references: Annotated[tuple[str, ...], Field(max_length=_MAX_EVIDENCE)]
    input_tokens: Annotated[int, Field(ge=0, le=5_120_000_000)]
    output_tokens: Annotated[int, Field(ge=0, le=5_120_000_000)]
    provider_call_count: Annotated[int, Field(ge=0, le=_MAX_EVIDENCE)]
    reviewer_call_count: Annotated[int, Field(ge=0, le=_MAX_EVIDENCE)]
    tool_execution_count: Annotated[int, Field(ge=0, le=_MAX_EVIDENCE)]
    retry_count: Annotated[int, Field(ge=0, le=_MAX_EVIDENCE)]
    provider_cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=24, decimal_places=8)]
    tool_cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=24, decimal_places=8)]
    retry_cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=24, decimal_places=8)]
    total_cost: Annotated[Decimal, Field(ge=Decimal("0"), max_digits=24, decimal_places=8)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_EVIDENCE)]
    calculated_at: datetime
    may_spend: Literal[False] = False
    may_assign: Literal[False] = False
    may_mutate_budget: Literal[False] = False
    may_persist: Literal[False] = False

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("calculated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_attribution(self) -> Self:
        if len(self.provider_references) != len(set(self.provider_references)):
            raise ValueError("provider references must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("cost attribution evidence identifiers must be unique")
        count = (
            self.provider_call_count
            + self.reviewer_call_count
            + self.tool_execution_count
            + self.retry_count
        )
        if count != len(self.evidence_ids):
            raise ValueError("cost attribution counts must match evidence")
        if self.total_cost != self.provider_cost + self.tool_cost + self.retry_cost:
            raise ValueError("total cost must match the attributed cost buckets")
        return self


class AgentCostAttributor:
    """Aggregate exact-scope evidence without persistence or execution authority."""

    def attribute(self, request: AgentCostAttributionRequest) -> AgentCostAttribution:
        if type(request) is not AgentCostAttributionRequest:
            raise TypeError("request must be a canonical AgentCostAttributionRequest")
        expected_scope = (
            request.project_id,
            request.task_id,
            request.run_id,
            request.agent_id,
            request.genome_version_id,
        )
        if any(
            (
                item.project_id,
                item.task_id,
                item.run_id,
                item.agent_id,
                item.genome_version_id,
            )
            != expected_scope
            for item in request.evidence
        ):
            raise ValueError("cost evidence must match the attribution scope")
        if any(item.observed_at > request.calculated_at for item in request.evidence):
            raise ValueError("cost evidence cannot be observed in the future")

        provider_sources = {
            CostAttributionSource.PROVIDER_CALL,
            CostAttributionSource.REVIEWER_CALL,
        }
        provider_cost = _sum_costs(request.evidence, provider_sources)
        tool_cost = _sum_costs(request.evidence, {CostAttributionSource.TOOL_EXECUTION})
        retry_cost = _sum_costs(request.evidence, {CostAttributionSource.RETRY})
        return AgentCostAttribution(
            project_id=request.project_id,
            task_id=request.task_id,
            run_id=request.run_id,
            agent_id=request.agent_id,
            genome_version_id=request.genome_version_id,
            provider_references=tuple(
                sorted(
                    {
                        item.provider_reference
                        for item in request.evidence
                        if item.provider_reference is not None
                    }
                )
            ),
            input_tokens=sum(item.input_tokens for item in request.evidence),
            output_tokens=sum(item.output_tokens for item in request.evidence),
            provider_call_count=_count(request.evidence, CostAttributionSource.PROVIDER_CALL),
            reviewer_call_count=_count(request.evidence, CostAttributionSource.REVIEWER_CALL),
            tool_execution_count=_count(request.evidence, CostAttributionSource.TOOL_EXECUTION),
            retry_count=_count(request.evidence, CostAttributionSource.RETRY),
            provider_cost=provider_cost,
            tool_cost=tool_cost,
            retry_cost=retry_cost,
            total_cost=(provider_cost + tool_cost + retry_cost).quantize(
                _MONEY_SCALE, rounding=ROUND_HALF_UP
            ),
            evidence_ids=tuple(item.evidence_id for item in request.evidence),
            calculated_at=request.calculated_at,
        )


def _sum_costs(
    evidence: tuple[AttributableCostEvidence, ...],
    sources: set[CostAttributionSource],
) -> Decimal:
    return sum(
        (item.cost for item in evidence if item.source in sources),
        Decimal("0"),
    ).quantize(_MONEY_SCALE, rounding=ROUND_HALF_UP)


def _count(evidence: tuple[AttributableCostEvidence, ...], source: CostAttributionSource) -> int:
    return sum(item.source is source for item in evidence)
