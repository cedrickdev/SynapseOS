"""Deterministic recovery recommendations for the future AI Manager."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from core.manager.blockers import ManagerBlockerCode, ManagerBlockerReport


class ManagerRecoveryAction(StrEnum):
    """Closed non-executing recovery recommendations."""

    NONE = "NONE"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"


class ManagerRecoveryRecommendation(BaseModel):
    """A side-effect-free Manager recovery recommendation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    action: ManagerRecoveryAction
    reason_codes: Annotated[tuple[ManagerBlockerCode, ...], Field(max_length=7)]


class ManagerRecoveryPlanner:
    """Map observed blockers to conservative recovery recommendations."""

    _ESCALATION_CODES = {
        ManagerBlockerCode.DEPENDENCY_BLOCKED,
        ManagerBlockerCode.PROVIDER_UNAVAILABLE,
        ManagerBlockerCode.SECURITY_HOLD,
        ManagerBlockerCode.APPROVAL_PENDING,
        ManagerBlockerCode.NO_ELIGIBLE_AGENT,
    }
    _REASSIGNMENT_CODES = {ManagerBlockerCode.NO_PROGRESS, ManagerBlockerCode.REVIEWER_BACKLOG}

    def recommend(self, report: ManagerBlockerReport) -> ManagerRecoveryRecommendation:
        """Return a deterministic recommendation without executing it."""
        if type(report) is not ManagerBlockerReport:
            raise TypeError("report must be a canonical ManagerBlockerReport")
        escalation_reasons = tuple(code for code in report.codes if code in self._ESCALATION_CODES)
        if escalation_reasons:
            return ManagerRecoveryRecommendation(
                action=ManagerRecoveryAction.ESCALATE,
                reason_codes=escalation_reasons,
            )
        reassignment_reasons = tuple(
            code for code in report.codes if code in self._REASSIGNMENT_CODES
        )
        if reassignment_reasons:
            return ManagerRecoveryRecommendation(
                action=ManagerRecoveryAction.REASSIGN,
                reason_codes=reassignment_reasons,
            )
        return ManagerRecoveryRecommendation(action=ManagerRecoveryAction.NONE, reason_codes=())
