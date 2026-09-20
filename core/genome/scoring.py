"""Deterministic, provider-neutral Agent Genome capability scoring."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.genome.evidence import EvidenceOutcome, EvidenceSignal, EvidenceSourceType

_CAPABILITY_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
_SCORE_QUANTUM = Decimal("0.0001")
_PRIOR_SUCCESS = Decimal("1")
_PRIOR_FAILURE = Decimal("1")
_CONFIDENCE_STRENGTH = Decimal("4")

_SOURCE_WEIGHTS = {
    EvidenceSourceType.AGENT_RUN: 1,
    EvidenceSourceType.PULL_REQUEST_REVIEW: 2,
    EvidenceSourceType.QA_APPROVAL: 2,
    EvidenceSourceType.SECURITY_APPROVAL: 3,
}
_SUCCESS_OUTCOMES = frozenset(
    {EvidenceOutcome.SUCCEEDED, EvidenceOutcome.APPROVED, EvidenceOutcome.PASSED}
)
_FAILURE_OUTCOMES = frozenset(
    {
        EvidenceOutcome.FAILED,
        EvidenceOutcome.TIMED_OUT,
        EvidenceOutcome.CHANGES_REQUESTED,
        EvidenceOutcome.REJECTED,
        EvidenceOutcome.BLOCKED,
    }
)
_EXPECTED_SIGNALS = {
    EvidenceSourceType.AGENT_RUN: EvidenceSignal.RUN_OUTCOME,
    EvidenceSourceType.PULL_REQUEST_REVIEW: EvidenceSignal.REVIEW_OUTCOME,
    EvidenceSourceType.QA_APPROVAL: EvidenceSignal.QA_OUTCOME,
    EvidenceSourceType.SECURITY_APPROVAL: EvidenceSignal.SECURITY_OUTCOME,
}
_EXPECTED_OUTCOMES = {
    EvidenceSourceType.AGENT_RUN: {
        EvidenceOutcome.SUCCEEDED,
        EvidenceOutcome.FAILED,
        EvidenceOutcome.CANCELLED,
        EvidenceOutcome.TIMED_OUT,
    },
    EvidenceSourceType.PULL_REQUEST_REVIEW: {
        EvidenceOutcome.APPROVED,
        EvidenceOutcome.CHANGES_REQUESTED,
    },
    EvidenceSourceType.QA_APPROVAL: {
        EvidenceOutcome.PASSED,
        EvidenceOutcome.REJECTED,
        EvidenceOutcome.BLOCKED,
    },
    EvidenceSourceType.SECURITY_APPROVAL: {
        EvidenceOutcome.PASSED,
        EvidenceOutcome.REJECTED,
        EvidenceOutcome.BLOCKED,
    },
}


class CapabilityScoringPolicy(StrEnum):
    """Versioned scoring policy retained with every calculated metric."""

    BAYESIAN_V1 = "BAYESIAN_V1"


class _StrictScoringModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CapabilityEvidence(_StrictScoringModel):
    """Minimal immutable observation accepted by the capability scorer."""

    evidence_id: UUID
    agent_id: UUID
    source_type: EvidenceSourceType
    signal: EvidenceSignal
    outcome: EvidenceOutcome
    observed_at: datetime

    @model_validator(mode="after")
    def require_scoreable_evidence_shape(self) -> Self:
        expected_signal = _EXPECTED_SIGNALS.get(self.source_type)
        if expected_signal is None or self.signal is not expected_signal:
            raise ValueError("capability scoring accepts only categorical outcome evidence")
        if self.outcome not in _EXPECTED_OUTCOMES[self.source_type]:
            raise ValueError("evidence outcome is not valid for capability scoring")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("capability evidence time must be timezone-aware")
        return self


class CapabilityScoringRequest(_StrictScoringModel):
    """Bounded evidence set explicitly attributed to one declared capability."""

    agent_id: UUID
    capability_key: Annotated[str, Field(pattern=_CAPABILITY_PATTERN, max_length=128)]
    evidence: Annotated[tuple[CapabilityEvidence, ...], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def require_one_agent_and_unique_evidence(self) -> Self:
        if any(item.agent_id != self.agent_id for item in self.evidence):
            raise ValueError("all capability evidence must belong to the requested agent")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("capability evidence identifiers must be unique")
        return self


class CapabilityEvidenceContribution(_StrictScoringModel):
    """Exact policy contribution retained for one used evidence row."""

    evidence_id: UUID
    weight: Annotated[int, Field(ge=1, le=3)]
    contribution: Annotated[int, Field(ge=0, le=1)]


class CapabilityScore(_StrictScoringModel):
    """Reproducible capability metric produced by one scoring policy."""

    agent_id: UUID
    capability_key: Annotated[str, Field(pattern=_CAPABILITY_PATTERN, max_length=128)]
    policy: CapabilityScoringPolicy
    score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=4)]
    confidence: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=4)]
    sample_count: Annotated[int, Field(ge=1, le=256)]
    success_count: Annotated[int, Field(ge=0, le=256)]
    failure_count: Annotated[int, Field(ge=0, le=256)]
    total_weight: Annotated[int, Field(ge=1, le=768)]
    last_observed_at: datetime
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=256)]
    contributions: Annotated[
        tuple[CapabilityEvidenceContribution, ...], Field(min_length=1, max_length=256)
    ]

    @model_validator(mode="after")
    def require_consistent_counts_and_provenance(self) -> Self:
        if self.success_count + self.failure_count != self.sample_count:
            raise ValueError("capability score counts must match sample count")
        if (
            len(self.evidence_ids) != self.sample_count
            or len(self.contributions) != self.sample_count
        ):
            raise ValueError("capability score provenance must match sample count")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("capability score evidence identifiers must be unique")
        contribution_ids = tuple(item.evidence_id for item in self.contributions)
        if contribution_ids != self.evidence_ids:
            raise ValueError("capability score contributions must match evidence order")
        if sum(item.weight for item in self.contributions) != self.total_weight:
            raise ValueError("capability score contribution weights must match total weight")
        if sum(item.contribution for item in self.contributions) != self.success_count:
            raise ValueError("capability score contributions must match success count")
        if self.last_observed_at.tzinfo is None or self.last_observed_at.utcoffset() is None:
            raise ValueError("capability score observation time must be timezone-aware")
        return self


class CapabilityScorer:
    """Calculate a conservative weighted Bayesian score without side effects."""

    def score(self, request: CapabilityScoringRequest) -> CapabilityScore:
        scored = tuple(
            sorted(
                (
                    item
                    for item in request.evidence
                    if item.outcome in _SUCCESS_OUTCOMES or item.outcome in _FAILURE_OUTCOMES
                ),
                key=lambda item: (item.observed_at, item.evidence_id),
            )
        )
        if not scored:
            raise ValueError("capability scoring requires at least one scorable outcome")

        success_count = sum(item.outcome in _SUCCESS_OUTCOMES for item in scored)
        failure_count = len(scored) - success_count
        weighted_success = sum(
            _SOURCE_WEIGHTS[item.source_type]
            for item in scored
            if item.outcome in _SUCCESS_OUTCOMES
        )
        total_weight = sum(_SOURCE_WEIGHTS[item.source_type] for item in scored)
        weighted_failure = total_weight - weighted_success
        posterior_total = (
            _PRIOR_SUCCESS + _PRIOR_FAILURE + Decimal(weighted_success + weighted_failure)
        )
        score = (_PRIOR_SUCCESS + Decimal(weighted_success)) / posterior_total
        confidence = Decimal(total_weight) / (Decimal(total_weight) + _CONFIDENCE_STRENGTH)

        return CapabilityScore(
            agent_id=request.agent_id,
            capability_key=request.capability_key,
            policy=CapabilityScoringPolicy.BAYESIAN_V1,
            score=score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
            confidence=confidence.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP),
            sample_count=len(scored),
            success_count=success_count,
            failure_count=failure_count,
            total_weight=total_weight,
            last_observed_at=max(item.observed_at for item in scored),
            evidence_ids=tuple(item.evidence_id for item in scored),
            contributions=tuple(
                CapabilityEvidenceContribution(
                    evidence_id=item.evidence_id,
                    weight=_SOURCE_WEIGHTS[item.source_type],
                    contribution=int(item.outcome in _SUCCESS_OUTCOMES),
                )
                for item in scored
            ),
        )
