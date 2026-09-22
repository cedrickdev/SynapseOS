"""Non-authorizing Agent Genome metrics for independently verified task outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_OBSERVATIONS = 512
_ALGORITHM_VERSION = "genome-outcome-integrity-v1"
_RATE_QUANTUM = Decimal("0.0001")
_RATE = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
]


class OutcomeVerificationSource(StrEnum):
    """Independent sources permitted to attest an observed task outcome."""

    REVIEW = "REVIEW"
    QA = "QA"
    SECURITY = "SECURITY"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


class OutcomeIntegrityProfileState(StrEnum):
    """Whether enough trusted observations exist to establish a profile."""

    COLD_START = "COLD_START"
    ESTABLISHED = "ESTABLISHED"


class _StrictOutcomeIntegrityModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class OutcomeIntegrityObservation(_StrictOutcomeIntegrityModel):
    """One independently verified comparison between proxy success and task outcome."""

    evidence_id: UUID
    project_id: UUID
    agent_id: UUID
    task_id: UUID
    run_id: UUID
    metric_success: bool
    acceptance_criteria_satisfied: bool
    objective_satisfied: bool
    completion_claimed: bool
    reopened_after_completion: bool
    verification_source: OutcomeVerificationSource
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_reopen_provenance(self) -> Self:
        if self.reopened_after_completion and not self.completion_claimed:
            raise ValueError("a reopened outcome requires a prior completion claim")
        return self


class AgentOutcomeIntegrityProfile(_StrictOutcomeIntegrityModel):
    """Versioned historical outcome measures that never grant authority."""

    agent_id: UUID
    genome_version_id: UUID
    profile_version: Annotated[int, Field(ge=1, le=1_000_000)]
    state: OutcomeIntegrityProfileState
    objective_alignment_rate: _RATE
    metric_gaming_incidents: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    acceptance_criteria_escape_rate: _RATE
    post_completion_reopen_rate: _RATE
    sample_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_OBSERVATIONS)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    calculated_at: datetime
    may_grant_authority: Literal[False] = False
    may_mutate_trust: Literal[False] = False
    may_mutate_runtime: Literal[False] = False

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("calculated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_state_and_evidence(self) -> Self:
        if self.sample_count != len(self.evidence_ids):
            raise ValueError("sample_count must match evidence_ids")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        if (self.state is OutcomeIntegrityProfileState.COLD_START) != (self.sample_count == 0):
            raise ValueError("cold-start state must match an empty sample")
        return self


class AgentOutcomeIntegrityProfileCalculator:
    """Aggregate bounded verified outcomes without changing Trust, authority, or runtime state."""

    def calculate(
        self,
        *,
        agent_id: UUID,
        genome_version_id: UUID,
        profile_version: int,
        observations: tuple[OutcomeIntegrityObservation, ...],
        calculated_at: datetime,
    ) -> AgentOutcomeIntegrityProfile:
        """Build a reproducible outcome-integrity profile from canonical observations."""
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not OutcomeIntegrityObservation for item in observations):
            raise TypeError("observations must be canonical OutcomeIntegrityObservation values")
        if any(item.agent_id != agent_id for item in observations):
            raise ValueError("observations must belong to the profile agent")
        evidence_ids = tuple(item.evidence_id for item in observations)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("observation evidence identifiers must be unique")
        if any(item.observed_at > calculated_at for item in observations):
            raise ValueError("outcome observations cannot follow profile calculation")

        sample_count = len(observations)
        completion_claims = tuple(item for item in observations if item.completion_claimed)
        return AgentOutcomeIntegrityProfile(
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            profile_version=profile_version,
            state=(
                OutcomeIntegrityProfileState.ESTABLISHED
                if observations
                else OutcomeIntegrityProfileState.COLD_START
            ),
            objective_alignment_rate=_rate(
                sum(item.objective_satisfied for item in observations), sample_count
            ),
            metric_gaming_incidents=sum(
                item.metric_success and not item.objective_satisfied for item in observations
            ),
            acceptance_criteria_escape_rate=_rate(
                sum(not item.acceptance_criteria_satisfied for item in completion_claims),
                len(completion_claims),
            ),
            post_completion_reopen_rate=_rate(
                sum(item.reopened_after_completion for item in completion_claims),
                len(completion_claims),
            ),
            sample_count=sample_count,
            evidence_ids=evidence_ids,
            algorithm_version=_ALGORITHM_VERSION,
            calculated_at=calculated_at,
        )


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _RATE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
