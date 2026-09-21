"""Tests for versioned Agent Genome behavioral baselines."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.genome import (
    BehaviorMetricObservation,
    GenomeBehavioralBaselineBuilder,
    GenomeBehavioralDeviationDetector,
    GenomeBehaviorMetric,
)


def test_large_tool_call_deviation_emits_a_governor_reevaluation_signal() -> None:
    """Critical runtime deviations are observable but do not execute governance changes."""
    agent_id = uuid4()
    baseline = GenomeBehavioralBaselineBuilder().build(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        baseline_version=1,
        observations=(
            BehaviorMetricObservation(
                evidence_id=uuid4(),
                agent_id=agent_id,
                metric=GenomeBehaviorMetric.TOOL_CALL_COUNT,
                value=Decimal("2"),
                observed_at=datetime.now(UTC),
            ),
            BehaviorMetricObservation(
                evidence_id=uuid4(),
                agent_id=agent_id,
                metric=GenomeBehaviorMetric.TOOL_CALL_COUNT,
                value=Decimal("3"),
                observed_at=datetime.now(UTC),
            ),
        ),
        created_at=datetime.now(UTC),
    )

    deviation = GenomeBehavioralDeviationDetector().detect(
        baseline,
        BehaviorMetricObservation(
            evidence_id=uuid4(),
            agent_id=agent_id,
            metric=GenomeBehaviorMetric.TOOL_CALL_COUNT,
            value=Decimal("9"),
            observed_at=datetime.now(UTC),
        ),
    )

    assert deviation.requires_governor_reevaluation is True
