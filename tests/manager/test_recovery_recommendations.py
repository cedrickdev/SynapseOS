"""Tests for deterministic Manager recovery recommendations."""

from __future__ import annotations

from core.manager import (
    ManagerBlockerCode,
    ManagerBlockerReport,
    ManagerRecoveryAction,
    ManagerRecoveryPlanner,
)


def test_security_hold_escalates_instead_of_recommending_reassignment() -> None:
    """Security holds are never resolved through automatic reassignment advice."""
    recommendation = ManagerRecoveryPlanner().recommend(
        ManagerBlockerReport(
            codes=(ManagerBlockerCode.NO_PROGRESS, ManagerBlockerCode.SECURITY_HOLD)
        )
    )

    assert recommendation.action is ManagerRecoveryAction.ESCALATE
    assert recommendation.reason_codes == (ManagerBlockerCode.SECURITY_HOLD,)
