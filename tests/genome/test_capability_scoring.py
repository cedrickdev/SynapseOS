"""Unit tests for deterministic Agent Genome capability scoring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.genome import EvidenceOutcome, EvidenceSignal, EvidenceSourceType
from core.genome.scoring import (
    CapabilityEvidence,
    CapabilityEvidenceContribution,
    CapabilityScore,
    CapabilityScorer,
    CapabilityScoringPolicy,
    CapabilityScoringRequest,
)


def _evidence(
    *,
    agent_id: uuid.UUID,
    source_type: EvidenceSourceType,
    signal: EvidenceSignal,
    outcome: EvidenceOutcome,
    observed_at: datetime,
) -> CapabilityEvidence:
    return CapabilityEvidence(
        evidence_id=uuid.uuid4(),
        agent_id=agent_id,
        source_type=source_type,
        signal=signal,
        outcome=outcome,
        observed_at=observed_at,
    )


def test_capability_score_uses_conservative_weighted_bayesian_policy() -> None:
    agent_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 14, 10, tzinfo=UTC)
    request = CapabilityScoringRequest(
        agent_id=agent_id,
        capability_key="python.fastapi",
        evidence=(
            _evidence(
                agent_id=agent_id,
                source_type=EvidenceSourceType.AGENT_RUN,
                signal=EvidenceSignal.RUN_OUTCOME,
                outcome=EvidenceOutcome.SUCCEEDED,
                observed_at=observed_at,
            ),
            _evidence(
                agent_id=agent_id,
                source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
                signal=EvidenceSignal.REVIEW_OUTCOME,
                outcome=EvidenceOutcome.APPROVED,
                observed_at=observed_at + timedelta(minutes=1),
            ),
            _evidence(
                agent_id=agent_id,
                source_type=EvidenceSourceType.QA_APPROVAL,
                signal=EvidenceSignal.QA_OUTCOME,
                outcome=EvidenceOutcome.REJECTED,
                observed_at=observed_at + timedelta(minutes=2),
            ),
        ),
    )

    result = CapabilityScorer().score(request)

    assert result.policy is CapabilityScoringPolicy.BAYESIAN_V1
    assert result.score == Decimal("0.5714")
    assert result.confidence == Decimal("0.5556")
    assert result.sample_count == 3
    assert result.success_count == 2
    assert result.failure_count == 1
    assert result.total_weight == 5
    assert result.last_observed_at == observed_at + timedelta(minutes=2)
    assert result.evidence_ids == tuple(item.evidence_id for item in request.evidence)


def test_capability_score_is_order_independent_and_excludes_cancelled_runs() -> None:
    agent_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 14, 10, tzinfo=UTC)
    succeeded = _evidence(
        agent_id=agent_id,
        source_type=EvidenceSourceType.SECURITY_APPROVAL,
        signal=EvidenceSignal.SECURITY_OUTCOME,
        outcome=EvidenceOutcome.PASSED,
        observed_at=observed_at,
    )
    cancelled = _evidence(
        agent_id=agent_id,
        source_type=EvidenceSourceType.AGENT_RUN,
        signal=EvidenceSignal.RUN_OUTCOME,
        outcome=EvidenceOutcome.CANCELLED,
        observed_at=observed_at + timedelta(minutes=1),
    )

    first = CapabilityScorer().score(
        CapabilityScoringRequest(
            agent_id=agent_id,
            capability_key="security.review",
            evidence=(cancelled, succeeded),
        )
    )
    second = CapabilityScorer().score(
        CapabilityScoringRequest(
            agent_id=agent_id,
            capability_key="security.review",
            evidence=(succeeded, cancelled),
        )
    )

    assert first == second
    assert first.score == Decimal("0.8000")
    assert first.confidence == Decimal("0.4286")
    assert first.sample_count == 1
    assert first.evidence_ids == (succeeded.evidence_id,)


def test_capability_scoring_request_rejects_untrusted_or_ambiguous_evidence() -> None:
    agent_id = uuid.uuid4()
    observed_at = datetime(2026, 9, 14, 10, tzinfo=UTC)
    valid = _evidence(
        agent_id=agent_id,
        source_type=EvidenceSourceType.AGENT_RUN,
        signal=EvidenceSignal.RUN_OUTCOME,
        outcome=EvidenceOutcome.SUCCEEDED,
        observed_at=observed_at,
    )
    usage_values = {
        "evidence_id": uuid.uuid4(),
        "agent_id": agent_id,
        "source_type": EvidenceSourceType.USAGE_RECORD,
        "signal": EvidenceSignal.TOTAL_TOKENS,
        "outcome": EvidenceOutcome.OBSERVED,
        "observed_at": observed_at,
    }

    with pytest.raises(ValidationError):
        CapabilityScoringRequest(
            agent_id=agent_id,
            capability_key="Python",
            evidence=(valid,),
        )
    with pytest.raises(ValidationError):
        CapabilityScoringRequest(
            agent_id=agent_id,
            capability_key="python",
            evidence=(valid, valid),
        )
    with pytest.raises(ValidationError):
        CapabilityScoringRequest(
            agent_id=agent_id,
            capability_key="python",
            evidence=(valid.model_copy(update={"agent_id": uuid.uuid4()}),),
        )
    with pytest.raises(ValidationError, match="categorical outcome evidence"):
        CapabilityEvidence.model_validate(usage_values)


def test_capability_scoring_requires_at_least_one_scored_outcome() -> None:
    agent_id = uuid.uuid4()
    cancelled = _evidence(
        agent_id=agent_id,
        source_type=EvidenceSourceType.AGENT_RUN,
        signal=EvidenceSignal.RUN_OUTCOME,
        outcome=EvidenceOutcome.CANCELLED,
        observed_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="scorable"):
        CapabilityScorer().score(
            CapabilityScoringRequest(
                agent_id=agent_id,
                capability_key="python",
                evidence=(cancelled,),
            )
        )


def test_capability_evidence_rejects_an_outcome_from_another_source_type() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            agent_id=uuid.uuid4(),
            source_type=EvidenceSourceType.AGENT_RUN,
            signal=EvidenceSignal.RUN_OUTCOME,
            outcome=EvidenceOutcome.APPROVED,
            observed_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
        )


def test_capability_score_contract_rejects_inconsistent_provenance_counts() -> None:
    agent_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    values = {
        "agent_id": agent_id,
        "capability_key": "python",
        "policy": CapabilityScoringPolicy.BAYESIAN_V1,
        "score": Decimal("0.5000"),
        "confidence": Decimal("0.2000"),
        "sample_count": 2,
        "success_count": 1,
        "failure_count": 0,
        "total_weight": 1,
        "last_observed_at": datetime(2026, 9, 14, 10, tzinfo=UTC),
        "evidence_ids": (evidence_id,),
        "contributions": (
            CapabilityEvidenceContribution(
                evidence_id=evidence_id,
                weight=1,
                contribution=1,
            ),
        ),
    }

    with pytest.raises(ValidationError):
        CapabilityScore.model_validate(values)
