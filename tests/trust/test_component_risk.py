"""Tests for deterministic component-risk Trust signals."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.component_trust import ComponentTrustLevel, ComponentType
from core.genome import ComponentUsageObservation, ComponentUsageOutcome
from core.trust.component_risk import (
    ComponentRiskAnalyzer,
    ComponentRiskObservation,
    ComponentRiskPolicy,
    ComponentRiskSeverity,
    ComponentRiskSignal,
)


def _observation(
    *,
    outcome: ComponentUsageOutcome,
    trust_level: ComponentTrustLevel = ComponentTrustLevel.APPROVED,
    observed_at: datetime,
    manifest_scanned_at: datetime,
) -> ComponentRiskObservation:
    component_id = uuid4()
    return ComponentRiskObservation(
        usage=ComponentUsageObservation(
            event_id=uuid4(),
            agent_id=uuid4(),
            project_id=uuid4(),
            task_id=uuid4(),
            agent_run_id=uuid4(),
            genome_version_id=uuid4(),
            component_manifest_id=uuid4(),
            component_id=component_id,
            outcome=outcome,
            observed_at=observed_at,
        ),
        component_type=ComponentType.SKILL,
        trust_level=trust_level,
        manifest_scanned_at=manifest_scanned_at,
    )


def test_analyzer_emits_restrictive_component_risk_signals() -> None:
    evaluated_at = datetime.now(UTC)
    agent_id = uuid4()
    component_id = uuid4()
    observations = []
    for outcome in (
        ComponentUsageOutcome.FAILED,
        ComponentUsageOutcome.FAILED,
        ComponentUsageOutcome.BLOCKED,
    ):
        item = _observation(
            outcome=outcome,
            trust_level=ComponentTrustLevel.RESTRICTED,
            observed_at=evaluated_at - timedelta(minutes=1),
            manifest_scanned_at=evaluated_at - timedelta(days=40),
        )
        observations.append(
            item.model_copy(
                update={
                    "usage": item.usage.model_copy(
                        update={"agent_id": agent_id, "component_id": component_id}
                    )
                }
            )
        )

    result = ComponentRiskAnalyzer().analyze(
        agent_id=agent_id,
        component_id=component_id,
        observations=tuple(observations),
        policy=ComponentRiskPolicy(
            max_manifest_age=timedelta(days=30),
            repeated_failure_threshold=2,
            repeated_block_threshold=1,
        ),
        evaluated_at=evaluated_at,
    )

    assert result.signals == (
        ComponentRiskSignal.RESTRICTED_COMPONENT_USED,
        ComponentRiskSignal.STALE_TRUST_MANIFEST,
        ComponentRiskSignal.REPEATED_COMPONENT_FAILURE,
        ComponentRiskSignal.REPEATED_COMPONENT_BLOCK,
    )
    assert result.severity is ComponentRiskSeverity.HIGH
    assert result.requires_governor_reevaluation is True
    assert result.may_mutate_trust is False
    assert result.may_mutate_permissions is False


def test_quarantined_component_is_critical_even_without_execution_success() -> None:
    evaluated_at = datetime.now(UTC)
    observation = _observation(
        outcome=ComponentUsageOutcome.BLOCKED,
        trust_level=ComponentTrustLevel.QUARANTINED,
        observed_at=evaluated_at,
        manifest_scanned_at=evaluated_at,
    )

    result = ComponentRiskAnalyzer().analyze(
        agent_id=observation.usage.agent_id,
        component_id=observation.usage.component_id,
        observations=(observation,),
        policy=ComponentRiskPolicy(),
        evaluated_at=evaluated_at,
    )

    assert ComponentRiskSignal.QUARANTINED_COMPONENT_USED in result.signals
    assert result.severity is ComponentRiskSeverity.CRITICAL


def test_analyzer_rejects_foreign_or_future_evidence() -> None:
    evaluated_at = datetime.now(UTC)
    observation = _observation(
        outcome=ComponentUsageOutcome.SUCCEEDED,
        observed_at=evaluated_at + timedelta(seconds=1),
        manifest_scanned_at=evaluated_at,
    )

    with pytest.raises(ValueError, match="follow evaluation"):
        ComponentRiskAnalyzer().analyze(
            agent_id=observation.usage.agent_id,
            component_id=observation.usage.component_id,
            observations=(observation,),
            policy=ComponentRiskPolicy(),
            evaluated_at=evaluated_at,
        )


def test_clean_approved_component_emits_no_signal() -> None:
    evaluated_at = datetime.now(UTC)
    observation = _observation(
        outcome=ComponentUsageOutcome.SUCCEEDED,
        observed_at=evaluated_at,
        manifest_scanned_at=evaluated_at,
    )

    result = ComponentRiskAnalyzer().analyze(
        agent_id=observation.usage.agent_id,
        component_id=observation.usage.component_id,
        observations=(observation,),
        policy=ComponentRiskPolicy(),
        evaluated_at=evaluated_at,
    )

    assert result.signals == ()
    assert result.severity is ComponentRiskSeverity.NONE
    assert result.requires_governor_reevaluation is False
