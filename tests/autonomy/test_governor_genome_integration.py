"""Tests for Agent Genome constraints in the Governor policy engine."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from core.agent_registry import AgentGenomeCapabilitySignal, AgentGenomeManagerSignal
from core.autonomy import (
    AutonomyLevel,
    AutonomyPolicyEngine,
    ExecutionEnvironment,
    GovernedActionType,
    Reversibility,
    RiskClassifier,
    RiskContext,
    RiskSeverity,
)
from core.autonomy.policy import PolicyReasonCode
from core.enums import ToolRiskLevel


def _context() -> RiskContext:
    return RiskContext(
        action_type=GovernedActionType.READ,
        tool_risk=ToolRiskLevel.LOW,
        environment=ExecutionEnvironment.LOCAL,
        data_sensitivity=RiskSeverity.NONE,
        blast_radius=RiskSeverity.NONE,
        reversibility=Reversibility.FULL,
        cost=RiskSeverity.NONE,
        external_side_effects=RiskSeverity.NONE,
        production_impact=RiskSeverity.NONE,
    )


def test_missing_or_weak_genome_evidence_caps_autonomy_at_observe() -> None:
    context = _context()
    genome_version_id = uuid4()
    genome_signal = AgentGenomeManagerSignal(
        agent_id=uuid4(),
        genome_version_id=genome_version_id,
        capabilities=(
            AgentGenomeCapabilitySignal(
                capability_key="database-migrations",
                score=Decimal("0.4000"),
                confidence=Decimal("1.0000"),
            ),
        ),
    )

    recommendation = AutonomyPolicyEngine().evaluate(
        context,
        RiskClassifier().classify(context),
        genome_signal=genome_signal,
        required_capabilities=("database-migrations",),
    )

    assert recommendation.maximum_autonomy_level is AutonomyLevel.OBSERVE
    assert PolicyReasonCode.GENOME_CAPABILITY_GAP in recommendation.reason_codes
    assert recommendation.genome_version_id == genome_version_id


def test_strong_genome_evidence_never_expands_the_existing_policy_ceiling() -> None:
    context = _context()
    genome_version_id = uuid4()
    genome_signal = AgentGenomeManagerSignal(
        agent_id=uuid4(),
        genome_version_id=genome_version_id,
        capabilities=(
            AgentGenomeCapabilitySignal(
                capability_key="database-migrations",
                score=Decimal("1.0000"),
                confidence=Decimal("1.0000"),
            ),
        ),
    )

    recommendation = AutonomyPolicyEngine().evaluate(
        context,
        RiskClassifier().classify(context),
        genome_signal=genome_signal,
        required_capabilities=("database-migrations",),
    )

    assert recommendation.maximum_autonomy_level is AutonomyLevel.BOUNDED_AUTONOMY
    assert PolicyReasonCode.GENOME_CAPABILITY_GAP not in recommendation.reason_codes
    assert recommendation.genome_version_id == genome_version_id
