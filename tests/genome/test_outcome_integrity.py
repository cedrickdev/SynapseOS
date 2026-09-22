"""Tests for Agent Genome outcome-integrity metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from core.genome import (
    AgentOutcomeIntegrityProfileCalculator,
    OutcomeIntegrityObservation,
    OutcomeIntegrityProfileState,
    OutcomeVerificationSource,
)


def test_green_metrics_without_objective_completion_reduce_integrity_profile() -> None:
    """A green proxy must not hide an escaped objective or post-completion reopen."""
    agent_id = uuid4()
    observations = (
        OutcomeIntegrityObservation(
            evidence_id=uuid4(),
            project_id=uuid4(),
            agent_id=agent_id,
            task_id=uuid4(),
            run_id=uuid4(),
            metric_success=True,
            acceptance_criteria_satisfied=True,
            objective_satisfied=True,
            completion_claimed=True,
            reopened_after_completion=False,
            verification_source=OutcomeVerificationSource.QA,
            evidence_reference="audit://outcome/verified-1",
            observed_at=datetime.now(UTC),
        ),
        OutcomeIntegrityObservation(
            evidence_id=uuid4(),
            project_id=uuid4(),
            agent_id=agent_id,
            task_id=uuid4(),
            run_id=uuid4(),
            metric_success=True,
            acceptance_criteria_satisfied=False,
            objective_satisfied=False,
            completion_claimed=True,
            reopened_after_completion=True,
            verification_source=OutcomeVerificationSource.HUMAN,
            evidence_reference="audit://outcome/reopened-2",
            observed_at=datetime.now(UTC),
        ),
    )

    profile = AgentOutcomeIntegrityProfileCalculator().calculate(
        agent_id=agent_id,
        genome_version_id=uuid4(),
        profile_version=1,
        observations=observations,
        calculated_at=datetime.now(UTC),
    )

    assert profile.state is OutcomeIntegrityProfileState.ESTABLISHED
    assert profile.objective_alignment_rate == Decimal("0.5000")
    assert profile.metric_gaming_incidents == 1
    assert profile.acceptance_criteria_escape_rate == Decimal("0.5000")
    assert profile.post_completion_reopen_rate == Decimal("0.5000")
    assert profile.sample_count == 2
    assert profile.may_grant_authority is False
