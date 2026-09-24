"""Deterministic non-authorizing Trust signals for component usage risk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.component_trust import ComponentTrustLevel, ComponentType
from core.genome import ComponentUsageObservation, ComponentUsageOutcome

_MAX_OBSERVATIONS = 128


class ComponentRiskSignal(StrEnum):
    """Closed evidence categories derived from exact component manifests and outcomes."""

    RESTRICTED_COMPONENT_USED = "RESTRICTED_COMPONENT_USED"
    QUARANTINED_COMPONENT_USED = "QUARANTINED_COMPONENT_USED"
    STALE_TRUST_MANIFEST = "STALE_TRUST_MANIFEST"
    REPEATED_COMPONENT_FAILURE = "REPEATED_COMPONENT_FAILURE"
    REPEATED_COMPONENT_BLOCK = "REPEATED_COMPONENT_BLOCK"


class ComponentRiskSeverity(StrEnum):
    """Highest deterministic risk found in the supplied evidence."""

    NONE = "NONE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class _StrictComponentRiskModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ComponentRiskPolicy(_StrictComponentRiskModel):
    """Bounded deterministic thresholds for component-risk classification."""

    max_manifest_age: Annotated[
        timedelta,
        Field(gt=timedelta(0), le=timedelta(days=365)),
    ] = timedelta(days=30)
    repeated_failure_threshold: Annotated[int, Field(ge=1, le=_MAX_OBSERVATIONS)] = 3
    repeated_block_threshold: Annotated[int, Field(ge=1, le=_MAX_OBSERVATIONS)] = 2
    algorithm_version: Literal["trust-component-risk-v1"] = "trust-component-risk-v1"


class ComponentRiskObservation(_StrictComponentRiskModel):
    """One usage event enriched only with its exact manifest classification."""

    usage: ComponentUsageObservation
    component_type: ComponentType
    trust_level: ComponentTrustLevel
    manifest_scanned_at: datetime

    @field_validator("manifest_scanned_at")
    @classmethod
    def validate_manifest_scanned_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("manifest_scanned_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_manifest_chronology(self) -> Self:
        if self.manifest_scanned_at > self.usage.observed_at:
            raise ValueError("component manifest scan cannot follow component usage")
        return self


class ComponentRiskResult(_StrictComponentRiskModel):
    """Explainable Trust evidence that cannot mutate Trust or authority."""

    agent_id: UUID
    component_id: UUID
    observations: Annotated[tuple[ComponentRiskObservation, ...], Field(max_length=128)]
    signals: Annotated[tuple[ComponentRiskSignal, ...], Field(max_length=5)]
    severity: ComponentRiskSeverity
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=128)]
    evaluated_at: datetime
    algorithm_version: Literal["trust-component-risk-v1"]
    requires_governor_reevaluation: bool
    may_mutate_trust: Literal[False] = False
    may_mutate_permissions: Literal[False] = False
    may_grant_authority: Literal[False] = False

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.evidence_ids != tuple(item.usage.event_id for item in self.observations):
            raise ValueError("evidence_ids must match component observations")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("component-risk evidence identifiers must be unique")
        if self.severity is not _severity_for(self.signals):
            raise ValueError("severity must match component-risk signals")
        if self.requires_governor_reevaluation != bool(self.signals):
            raise ValueError("Governor re-evaluation must match component-risk signals")
        return self


class ComponentRiskAnalyzer:
    """Classify exact component evidence without changing Trust or runtime state."""

    def analyze(
        self,
        *,
        agent_id: UUID,
        component_id: UUID,
        observations: tuple[ComponentRiskObservation, ...],
        policy: ComponentRiskPolicy,
        evaluated_at: datetime,
    ) -> ComponentRiskResult:
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not ComponentRiskObservation for item in observations):
            raise TypeError("observations must be canonical ComponentRiskObservation values")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ValueError("evaluated_at must be UTC-aware")
        if any(item.usage.agent_id != agent_id for item in observations):
            raise ValueError("observations must belong to the evaluated agent")
        if any(item.usage.component_id != component_id for item in observations):
            raise ValueError("observations must belong to the evaluated component")
        if any(item.usage.observed_at > evaluated_at for item in observations):
            raise ValueError("component-risk observations cannot follow evaluation")
        evidence_ids = tuple(item.usage.event_id for item in observations)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("component-risk evidence identifiers must be unique")

        signals: list[ComponentRiskSignal] = []
        trust_levels = {item.trust_level for item in observations}
        if ComponentTrustLevel.QUARANTINED in trust_levels:
            signals.append(ComponentRiskSignal.QUARANTINED_COMPONENT_USED)
        elif ComponentTrustLevel.RESTRICTED in trust_levels:
            signals.append(ComponentRiskSignal.RESTRICTED_COMPONENT_USED)
        if any(
            evaluated_at - item.manifest_scanned_at > policy.max_manifest_age
            for item in observations
        ):
            signals.append(ComponentRiskSignal.STALE_TRUST_MANIFEST)
        if (
            sum(item.usage.outcome is ComponentUsageOutcome.FAILED for item in observations)
            >= policy.repeated_failure_threshold
        ):
            signals.append(ComponentRiskSignal.REPEATED_COMPONENT_FAILURE)
        if (
            sum(item.usage.outcome is ComponentUsageOutcome.BLOCKED for item in observations)
            >= policy.repeated_block_threshold
        ):
            signals.append(ComponentRiskSignal.REPEATED_COMPONENT_BLOCK)

        result_signals = tuple(signals)
        return ComponentRiskResult(
            agent_id=agent_id,
            component_id=component_id,
            observations=observations,
            signals=result_signals,
            severity=_severity_for(result_signals),
            evidence_ids=evidence_ids,
            evaluated_at=evaluated_at,
            algorithm_version=policy.algorithm_version,
            requires_governor_reevaluation=bool(result_signals),
        )


def _severity_for(signals: tuple[ComponentRiskSignal, ...]) -> ComponentRiskSeverity:
    if ComponentRiskSignal.QUARANTINED_COMPONENT_USED in signals:
        return ComponentRiskSeverity.CRITICAL
    high = {
        ComponentRiskSignal.RESTRICTED_COMPONENT_USED,
        ComponentRiskSignal.STALE_TRUST_MANIFEST,
        ComponentRiskSignal.REPEATED_COMPONENT_FAILURE,
        ComponentRiskSignal.REPEATED_COMPONENT_BLOCK,
    }
    if high.intersection(signals):
        return ComponentRiskSeverity.HIGH
    if signals:
        return ComponentRiskSeverity.ELEVATED
    return ComponentRiskSeverity.NONE
