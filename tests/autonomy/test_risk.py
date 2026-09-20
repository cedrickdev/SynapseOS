"""Tests for deterministic Autonomy Governor risk classification."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.autonomy.risk import (
    ExecutionEnvironment,
    GovernedActionType,
    Reversibility,
    RiskClassifier,
    RiskContext,
    RiskLevel,
    RiskReasonCode,
    RiskSeverity,
)
from core.enums import ToolRiskLevel


def _context(**changes: object) -> RiskContext:
    values: dict[str, object] = {
        "action_type": GovernedActionType.READ,
        "tool_risk": ToolRiskLevel.LOW,
        "environment": ExecutionEnvironment.LOCAL,
        "data_sensitivity": RiskSeverity.NONE,
        "blast_radius": RiskSeverity.NONE,
        "reversibility": Reversibility.FULL,
        "cost": RiskSeverity.NONE,
        "external_side_effects": RiskSeverity.NONE,
        "production_impact": RiskSeverity.NONE,
    }
    values.update(changes)
    return RiskContext.model_validate(values)


def test_classifier_marks_a_local_read_as_low_risk() -> None:
    assessment = RiskClassifier().classify(_context())

    assert assessment.level is RiskLevel.LOW
    assert assessment.score == Decimal("0.25")
    assert assessment.reason_codes == (RiskReasonCode.TOOL_RISK,)


def test_classifier_marks_a_production_database_migration_as_critical() -> None:
    assessment = RiskClassifier().classify(
        _context(
            action_type=GovernedActionType.DATABASE_MIGRATION,
            environment=ExecutionEnvironment.PRODUCTION,
            production_impact=RiskSeverity.HIGH,
        )
    )

    assert assessment.level is RiskLevel.CRITICAL
    assert assessment.score == Decimal("1.00")
    assert RiskReasonCode.PRODUCTION_CRITICAL_ACTION in assessment.reason_codes


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"action_type": GovernedActionType.FINANCIAL_TRANSACTION}, RiskReasonCode.ACTION_TYPE),
        ({"tool_risk": ToolRiskLevel.CRITICAL}, RiskReasonCode.TOOL_RISK),
        ({"environment": ExecutionEnvironment.PRODUCTION}, RiskReasonCode.ENVIRONMENT),
        ({"data_sensitivity": RiskSeverity.CRITICAL}, RiskReasonCode.DATA_SENSITIVITY),
        ({"blast_radius": RiskSeverity.CRITICAL}, RiskReasonCode.BLAST_RADIUS),
        ({"reversibility": Reversibility.IRREVERSIBLE}, RiskReasonCode.IRREVERSIBILITY),
        ({"cost": RiskSeverity.CRITICAL}, RiskReasonCode.COST),
        ({"external_side_effects": RiskSeverity.CRITICAL}, RiskReasonCode.EXTERNAL_SIDE_EFFECTS),
        ({"production_impact": RiskSeverity.CRITICAL}, RiskReasonCode.PRODUCTION_IMPACT),
    ],
)
def test_classifier_accounts_for_every_required_risk_input(
    changes: dict[str, object],
    reason_code: RiskReasonCode,
) -> None:
    assessment = RiskClassifier().classify(_context(**changes))

    assert assessment.level is RiskLevel.CRITICAL
    assert assessment.score == Decimal("1.00")
    assert reason_code in assessment.reason_codes


def test_context_rejects_unrecognized_risk_inputs() -> None:
    with pytest.raises(ValidationError):
        _context(environment="production")
