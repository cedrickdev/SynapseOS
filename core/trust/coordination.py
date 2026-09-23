"""Deterministic, non-authorizing Trust signals for coordination risk."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.genome import CollaborationBaseline, CollaborationChannel, CollaborationObservation

_MAX_OBSERVATIONS = 128


class CoordinationRiskSignal(StrEnum):
    """Closed evidence categories for collusion and coordination risk."""

    UNAUTHORIZED_PEER_COMMUNICATION = "UNAUTHORIZED_PEER_COMMUNICATION"
    COORDINATED_POLICY_VIOLATION = "COORDINATED_POLICY_VIOLATION"
    REPEATED_SHARED_WORKAROUND = "REPEATED_SHARED_WORKAROUND"
    SUSPICIOUS_INFORMATION_PROPAGATION = "SUSPICIOUS_INFORMATION_PROPAGATION"
    UNAUTHORIZED_EXTERNAL_CHANNEL = "UNAUTHORIZED_EXTERNAL_CHANNEL"


class CoordinationRiskSeverity(StrEnum):
    """Highest deterministic risk level found in the supplied evidence."""

    NONE = "NONE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class _StrictCoordinationRiskModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CoordinationRiskObservation(_StrictCoordinationRiskModel):
    """One policy-enriched collaboration fact without retained message content."""

    collaboration: CollaborationObservation
    peer_authorized: bool
    channel_authorized: bool
    coordinated_policy_violation: bool
    shared_workaround: bool
    suspicious_information_propagation: bool


class CoordinationRiskResult(_StrictCoordinationRiskModel):
    """Explainable coordination-risk evidence that cannot grant or mutate authority."""

    baseline: CollaborationBaseline
    observations: Annotated[tuple[CoordinationRiskObservation, ...], Field(max_length=128)]
    signals: Annotated[tuple[CoordinationRiskSignal, ...], Field(max_length=5)]
    severity: CoordinationRiskSeverity
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=128)]
    evaluated_at: datetime
    requires_governor_reevaluation: bool
    may_mutate_trust: Literal[False] = False
    may_mutate_permissions: Literal[False] = False
    may_authorize_communication: Literal[False] = False

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("coordination-risk evidence identifiers must be unique")
        if self.evidence_ids != tuple(item.collaboration.evidence_id for item in self.observations):
            raise ValueError("evidence_ids must match observations")
        expected_severity = _severity_for(self.signals)
        if self.severity is not expected_severity:
            raise ValueError("severity must match emitted coordination-risk signals")
        if self.requires_governor_reevaluation != bool(self.signals):
            raise ValueError("Governor re-evaluation must match coordination-risk signals")
        return self


class CoordinationRiskAnalyzer:
    """Classify explicit coordination-policy facts without inferring authorization."""

    def analyze(
        self,
        baseline: CollaborationBaseline,
        *,
        observations: tuple[CoordinationRiskObservation, ...],
        evaluated_at: datetime,
    ) -> CoordinationRiskResult:
        """Return stable bounded signals while treating the baseline as context only."""
        if type(baseline) is not CollaborationBaseline:
            raise TypeError("baseline must be a canonical CollaborationBaseline")
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not CoordinationRiskObservation for item in observations):
            raise TypeError("observations must be canonical CoordinationRiskObservation values")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ValueError("evaluated_at must be UTC-aware")
        if baseline.created_at > evaluated_at:
            raise ValueError("collaboration baseline cannot follow evaluation")
        if any(item.collaboration.agent_id != baseline.agent_id for item in observations):
            raise ValueError("observations must belong to the baseline agent")
        if any(item.collaboration.observed_at > evaluated_at for item in observations):
            raise ValueError("coordination-risk observations cannot follow evaluation")
        evidence_ids = tuple(item.collaboration.evidence_id for item in observations)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("coordination-risk evidence identifiers must be unique")

        signals: list[CoordinationRiskSignal] = []
        if any(not item.peer_authorized for item in observations):
            signals.append(CoordinationRiskSignal.UNAUTHORIZED_PEER_COMMUNICATION)
        if any(item.coordinated_policy_violation for item in observations):
            signals.append(CoordinationRiskSignal.COORDINATED_POLICY_VIOLATION)
        if sum(item.shared_workaround for item in observations) >= 2:
            signals.append(CoordinationRiskSignal.REPEATED_SHARED_WORKAROUND)
        if any(item.suspicious_information_propagation for item in observations):
            signals.append(CoordinationRiskSignal.SUSPICIOUS_INFORMATION_PROPAGATION)
        if any(
            item.collaboration.channel is CollaborationChannel.EXTERNAL
            and not item.channel_authorized
            for item in observations
        ):
            signals.append(CoordinationRiskSignal.UNAUTHORIZED_EXTERNAL_CHANNEL)

        result_signals = tuple(signals)
        return CoordinationRiskResult(
            baseline=baseline,
            observations=observations,
            signals=result_signals,
            severity=_severity_for(result_signals),
            evidence_ids=evidence_ids,
            evaluated_at=evaluated_at,
            requires_governor_reevaluation=bool(result_signals),
        )


def _severity_for(signals: tuple[CoordinationRiskSignal, ...]) -> CoordinationRiskSeverity:
    critical = {
        CoordinationRiskSignal.COORDINATED_POLICY_VIOLATION,
        CoordinationRiskSignal.UNAUTHORIZED_EXTERNAL_CHANNEL,
    }
    if critical.intersection(signals):
        return CoordinationRiskSeverity.CRITICAL
    if signals:
        return CoordinationRiskSeverity.ELEVATED
    return CoordinationRiskSeverity.NONE
