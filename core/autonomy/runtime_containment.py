"""Immediate, non-mutating runtime downgrade and quarantine decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.autonomy.runtime_trust import GovernorRuntimeTrustEvaluation
from core.autonomy.types import AutonomyLevel


class RuntimeContainmentDisposition(StrEnum):
    """Closed containment actions that can only reduce effective autonomy."""

    DOWNGRADE = "DOWNGRADE"
    QUARANTINE = "QUARANTINE"


class RuntimeContainmentReason(StrEnum):
    """Closed evidence categories for an immediate runtime restriction."""

    RUNTIME_TRUST_DEGRADATION = "RUNTIME_TRUST_DEGRADATION"
    CRITICAL_INCIDENT = "CRITICAL_INCIDENT"
    SECURITY_ANOMALY = "SECURITY_ANOMALY"
    COMPROMISED_CREDENTIALS = "COMPROMISED_CREDENTIALS"
    SUSPICIOUS_TOOL_USE = "SUSPICIOUS_TOOL_USE"
    SEVERE_POLICY_VIOLATION = "SEVERE_POLICY_VIOLATION"


class _StrictContainmentModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class RuntimeContainmentSignal(_StrictContainmentModel):
    """One source-linked restriction signal for a specific active-run action."""

    agent_id: UUID
    run_id: UUID
    action_sequence: Annotated[int, Field(ge=1, le=10000)]
    disposition: RuntimeContainmentDisposition
    reason: RuntimeContainmentReason
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class GovernorRuntimeContainmentEvaluation(_StrictContainmentModel):
    """A monotone autonomy restriction without authority or execution side effects."""

    base_evaluation: GovernorRuntimeTrustEvaluation
    signal: RuntimeContainmentSignal
    previous_maximum_autonomy_level: AutonomyLevel
    effective_maximum_autonomy_level: AutonomyLevel
    quarantine_required: bool
    write_execution_restricted: bool
    manager_reassignment_recommended: bool
    requires_permission_recheck: Literal[True] = True
    may_execute: Literal[False] = False
    may_mutate_permissions: Literal[False] = False
    may_revoke_credentials: Literal[False] = False


class GovernorRuntimeContainmentEvaluator:
    """Apply an immediate bounded downgrade while leaving enforcement to authorities."""

    _LEVEL_ORDER = {
        AutonomyLevel.DISABLED: 0,
        AutonomyLevel.OBSERVE: 1,
        AutonomyLevel.RECOMMEND: 2,
        AutonomyLevel.ACT_WITH_APPROVAL: 3,
        AutonomyLevel.BOUNDED_AUTONOMY: 4,
        AutonomyLevel.HIGH_AUTONOMY: 5,
    }

    def evaluate(
        self,
        evaluation: GovernorRuntimeTrustEvaluation,
        *,
        signal: RuntimeContainmentSignal,
    ) -> GovernorRuntimeContainmentEvaluation:
        """Return a run-bound restriction that never expands or directly enforces authority."""
        if type(evaluation) is not GovernorRuntimeTrustEvaluation:
            raise TypeError("evaluation must be a canonical GovernorRuntimeTrustEvaluation")
        if type(signal) is not RuntimeContainmentSignal:
            raise TypeError("signal must be a canonical RuntimeContainmentSignal")

        request = evaluation.base_evaluation.request
        if signal.agent_id != request.agent_id or signal.run_id != request.run_id:
            raise ValueError("containment signal must belong to the evaluated agent and run")
        if signal.action_sequence != request.action_sequence:
            raise ValueError("containment signal must belong to the evaluated action")
        if signal.observed_at > request.evaluated_at:
            raise ValueError("containment signal cannot be observed after action evaluation")

        previous = evaluation.effective_maximum_autonomy_level
        ceiling = (
            AutonomyLevel.DISABLED
            if signal.disposition is RuntimeContainmentDisposition.QUARANTINE
            else AutonomyLevel.ACT_WITH_APPROVAL
        )
        effective = (
            ceiling if self._LEVEL_ORDER[ceiling] < self._LEVEL_ORDER[previous] else previous
        )
        quarantine = signal.disposition is RuntimeContainmentDisposition.QUARANTINE
        return GovernorRuntimeContainmentEvaluation(
            base_evaluation=evaluation,
            signal=signal,
            previous_maximum_autonomy_level=previous,
            effective_maximum_autonomy_level=effective,
            quarantine_required=quarantine,
            write_execution_restricted=effective
            in {AutonomyLevel.DISABLED, AutonomyLevel.OBSERVE, AutonomyLevel.RECOMMEND},
            manager_reassignment_recommended=quarantine,
        )
