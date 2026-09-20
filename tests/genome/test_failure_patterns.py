"""Unit tests for deterministic Agent Genome failure-pattern tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from core.genome import (
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    FailurePatternAnalyzer,
    FailurePatternObservation,
    GenomeFailureSeverity,
)


def _observation(
    *,
    source_type: EvidenceSourceType,
    signal: EvidenceSignal,
    outcome: EvidenceOutcome,
    agent_id: UUID | None = None,
    observed_at: datetime | None = None,
) -> FailurePatternObservation:
    return FailurePatternObservation(
        evidence_id=uuid4(),
        agent_id=agent_id or uuid4(),
        source_type=source_type,
        signal=signal,
        outcome=outcome,
        observed_at=observed_at or datetime(2026, 9, 20, 12, tzinfo=UTC),
    )


def test_analyzer_groups_recurring_failures_with_severity_and_last_seen() -> None:
    agent_id = uuid4()
    observations = (
        _observation(
            agent_id=agent_id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.CHANGES_REQUESTED,
            observed_at=datetime(2026, 9, 18, tzinfo=UTC),
        ),
        _observation(
            agent_id=agent_id,
            source_type=EvidenceSourceType.PULL_REQUEST_REVIEW,
            signal=EvidenceSignal.REVIEW_OUTCOME,
            outcome=EvidenceOutcome.CHANGES_REQUESTED,
            observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        ),
        _observation(
            agent_id=agent_id,
            source_type=EvidenceSourceType.SECURITY_APPROVAL,
            signal=EvidenceSignal.SECURITY_OUTCOME,
            outcome=EvidenceOutcome.BLOCKED,
        ),
        _observation(
            agent_id=agent_id,
            source_type=EvidenceSourceType.QA_APPROVAL,
            signal=EvidenceSignal.QA_OUTCOME,
            outcome=EvidenceOutcome.PASSED,
        ),
    )

    patterns = FailurePatternAnalyzer().analyze(observations)

    assert [(pattern.pattern_key, pattern.count) for pattern in patterns] == [
        ("review.changes_requested", 2),
        ("security.blocked", 1),
    ]
    assert patterns[0].severity is GenomeFailureSeverity.MEDIUM
    assert patterns[0].last_seen_at == datetime(2026, 9, 20, tzinfo=UTC)
    assert patterns[1].severity is GenomeFailureSeverity.CRITICAL


def test_analyzer_ignores_successes_and_cancelled_runs() -> None:
    agent_id = uuid4()
    patterns = FailurePatternAnalyzer().analyze(
        (
            _observation(
                source_type=EvidenceSourceType.AGENT_RUN,
                signal=EvidenceSignal.RUN_OUTCOME,
                outcome=EvidenceOutcome.SUCCEEDED,
                agent_id=agent_id,
            ),
            _observation(
                source_type=EvidenceSourceType.AGENT_RUN,
                signal=EvidenceSignal.RUN_OUTCOME,
                outcome=EvidenceOutcome.CANCELLED,
                agent_id=agent_id,
            ),
        )
    )

    assert patterns == ()


def test_analyzer_rejects_mixed_agents() -> None:
    first = uuid4()
    second = uuid4()

    try:
        FailurePatternAnalyzer().analyze(
            (
                _observation(
                    agent_id=first,
                    source_type=EvidenceSourceType.QA_APPROVAL,
                    signal=EvidenceSignal.QA_OUTCOME,
                    outcome=EvidenceOutcome.REJECTED,
                ),
                _observation(
                    agent_id=second,
                    source_type=EvidenceSourceType.QA_APPROVAL,
                    signal=EvidenceSignal.QA_OUTCOME,
                    outcome=EvidenceOutcome.REJECTED,
                ),
            )
        )
    except ValueError as error:
        assert "one agent" in str(error)
    else:
        raise AssertionError("mixed-agent evidence must be rejected")
