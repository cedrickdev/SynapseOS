"""Immutable Phase 28 registry and matching contracts."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.domain_decomposition import DomainWorkstream
from core.enums import AgentSeniority, AgentStatus, Permission, ToolRiskLevel

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Score = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)]


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentCapabilitySnapshot(_ImmutableModel):
    """One active capability and its measured expertise."""

    name: Identifier
    expertise: Score


class AgentCandidate(_ImmutableModel):
    """Bounded trusted agent snapshot consumed by the matcher."""

    agent_id: uuid.UUID
    slug: Identifier
    seniority: AgentSeniority
    status: AgentStatus
    autonomy_level: Annotated[int, Field(ge=0, le=5)]
    reputation: Score
    reliability: Score
    capabilities: Annotated[tuple[AgentCapabilitySnapshot, ...], Field(max_length=64)]
    active_permissions: Annotated[tuple[Permission, ...], Field(max_length=64)]

    @field_validator("capabilities", "active_permissions", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_members(self) -> Self:
        capability_names = tuple(capability.name.casefold() for capability in self.capabilities)
        if len(capability_names) != len(set(capability_names)):
            raise ValueError("candidate capabilities must be unique")
        if len(self.active_permissions) != len(set(self.active_permissions)):
            raise ValueError("candidate permissions must be unique")
        return self


class AgentCostEstimate(_ImmutableModel):
    """Task-local normalized cost; zero is cheapest and one is most expensive."""

    agent_id: uuid.UUID
    normalized_cost: Score


class AgentMatchingRequest(_ImmutableModel):
    """Explicit constraints for one workstream matching decision."""

    project_id: uuid.UUID
    workstream: DomainWorkstream
    required_permissions: Annotated[tuple[Permission, ...], Field(max_length=32)]
    minimum_seniority: AgentSeniority
    risk_level: ToolRiskLevel
    cost_estimates: Annotated[tuple[AgentCostEstimate, ...], Field(max_length=100)]
    limit: Annotated[int, Field(ge=1, le=100)] = 10

    @field_validator("required_permissions", "cost_estimates", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_members(self) -> Self:
        if len(self.required_permissions) != len(set(self.required_permissions)):
            raise ValueError("required permissions must be unique")
        cost_ids = tuple(estimate.agent_id for estimate in self.cost_estimates)
        if len(cost_ids) != len(set(cost_ids)):
            raise ValueError("cost estimates must identify unique agents")
        return self


class AgentMatchScore(_ImmutableModel):
    """Deterministic score inputs retained for explainability."""

    expertise: Score
    reputation: Score
    reliability: Score
    seniority_fit: Score
    cost_efficiency: Score


class RankedAgentMatch(_ImmutableModel):
    """Eligible candidate, score, and deterministic explanation."""

    agent: AgentCandidate
    score: Score
    breakdown: AgentMatchScore
    explanation: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]


class RejectedAgentMatch(_ImmutableModel):
    """Ineligible candidate with bounded fail-closed reasons."""

    agent_id: uuid.UUID
    reasons: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]


class AgentMatchingResult(_ImmutableModel):
    """Bounded Phase 28 matching result without assignment side effects."""

    workstream_id: Identifier
    matches: Annotated[tuple[RankedAgentMatch, ...], Field(max_length=100)]
    rejections: Annotated[tuple[RejectedAgentMatch, ...], Field(max_length=100)]
