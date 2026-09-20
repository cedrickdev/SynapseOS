"""Tests for Trust constraints in the non-authorizing Governor policy engine."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

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
from core.trust import TrustClass
from core.trust.governor_signal import TrustGovernorSignal, TrustGovernorSignalDisposition


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


def test_trust_restriction_caps_an_otherwise_low_risk_action_at_observe() -> None:
    context = _context()
    critical_event_id = uuid4()
    trust_signal = TrustGovernorSignal(
        overall_score=Decimal("20.00"),
        trust_class=TrustClass.LOW,
        trust_algorithm_version="trust-v1",
        disposition=TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED,
        requires_governor_recomputation=True,
        critical_event_id=critical_event_id,
    )

    recommendation = AutonomyPolicyEngine().evaluate(
        context,
        RiskClassifier().classify(context),
        trust_signal=trust_signal,
    )

    assert recommendation.maximum_autonomy_level is AutonomyLevel.OBSERVE
    assert PolicyReasonCode.TRUST_RESTRICTION in recommendation.reason_codes
    assert recommendation.trust_critical_event_id == critical_event_id
    assert recommendation.trust_algorithm_version == "trust-v1"


def test_neutral_trust_never_expands_the_risk_policy_ceiling() -> None:
    context = RiskContext(
        action_type=GovernedActionType.READ,
        tool_risk=ToolRiskLevel.HIGH,
        environment=ExecutionEnvironment.LOCAL,
        data_sensitivity=RiskSeverity.NONE,
        blast_radius=RiskSeverity.NONE,
        reversibility=Reversibility.FULL,
        cost=RiskSeverity.NONE,
        external_side_effects=RiskSeverity.NONE,
        production_impact=RiskSeverity.NONE,
    )
    neutral_signal = TrustGovernorSignal(
        overall_score=Decimal("100.00"),
        trust_class=TrustClass.HIGH,
        trust_algorithm_version="trust-v1",
        disposition=TrustGovernorSignalDisposition.NEUTRAL,
        requires_governor_recomputation=False,
        critical_event_id=None,
    )

    recommendation = AutonomyPolicyEngine().evaluate(
        context,
        RiskClassifier().classify(context),
        trust_signal=neutral_signal,
    )

    assert recommendation.maximum_autonomy_level is AutonomyLevel.RECOMMEND
    assert PolicyReasonCode.TRUST_RESTRICTION not in recommendation.reason_codes
    assert recommendation.trust_critical_event_id is None


def test_restriction_signal_without_critical_provenance_is_rejected() -> None:
    context = _context()
    invalid_signal = TrustGovernorSignal(
        overall_score=Decimal("20.00"),
        trust_class=TrustClass.LOW,
        trust_algorithm_version="trust-v1",
        disposition=TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED,
        requires_governor_recomputation=False,
        critical_event_id=None,
    )

    with pytest.raises(ValueError, match="provenance"):
        AutonomyPolicyEngine().evaluate(
            context,
            RiskClassifier().classify(context),
            trust_signal=invalid_signal,
        )
