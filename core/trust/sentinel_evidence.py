"""Independent, bounded Sentinel evidence ingestion for Trust evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.sentinel import SentinelRiskSignal


class SentinelEvidenceSeverity(StrEnum):
    """Highest deterministic severity among peer-confirmed Sentinel signals."""

    NONE = "NONE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class _StrictSentinelEvidenceModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class SentinelPeerAttestation(_StrictSentinelEvidenceModel):
    """Independent peer confirmation of a bounded Sentinel submission."""

    peer_auditor_agent_id: UUID
    audit_reference: Annotated[str, Field(min_length=1, max_length=512)]
    evidence_references: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    confirmed_signals: Annotated[tuple[SentinelRiskSignal, ...], Field(max_length=7)]
    independently_auditable: bool
    reviewed_at: datetime

    @field_validator("reviewed_at")
    @classmethod
    def validate_reviewed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reviewed_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
        groups: tuple[tuple[object, ...], ...] = (
            self.evidence_references,
            self.confirmed_signals,
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("Sentinel attestation evidence and signals must be unique")
        if any(
            not value or value != value.strip() or any(ord(character) < 32 for character in value)
            for value in (self.audit_reference, *self.evidence_references)
        ):
            raise ValueError("Sentinel attestation references must be content-safe")
        return self


class SentinelEvidenceSubmission(_StrictSentinelEvidenceModel):
    """Canonical boundary projection of one independently coordinated Sentinel review."""

    target_agent_id: UUID
    primary_sentinel_agent_id: UUID
    selected_peer_auditor_agent_id: UUID
    audit_reference: Annotated[str, Field(min_length=1, max_length=512)]
    evidence_references: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    submitted_signals: Annotated[tuple[SentinelRiskSignal, ...], Field(min_length=1, max_length=7)]
    submitted_at: datetime

    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("submitted_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_submission(self) -> Self:
        identities = {
            self.target_agent_id,
            self.primary_sentinel_agent_id,
            self.selected_peer_auditor_agent_id,
        }
        if len(identities) != 3:
            raise ValueError("target, primary Sentinel, and peer auditor must be independent")
        groups: tuple[tuple[object, ...], ...] = (
            self.evidence_references,
            self.submitted_signals,
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("Sentinel submission evidence and signals must be unique")
        return self


class SentinelTrustEvidence(_StrictSentinelEvidenceModel):
    """Peer-confirmed Trust evidence with no direct authority."""

    target_agent_id: UUID
    primary_sentinel_agent_id: UUID
    peer_auditor_agent_id: UUID
    audit_reference: str
    evidence_references: Annotated[tuple[str, ...], Field(max_length=256)]
    accepted_signals: Annotated[tuple[SentinelRiskSignal, ...], Field(max_length=7)]
    severity: SentinelEvidenceSeverity
    submitted_at: datetime
    reviewed_at: datetime
    ingested_at: datetime
    algorithm_version: Literal["trust-sentinel-evidence-v1"] = "trust-sentinel-evidence-v1"
    requires_governor_reevaluation: bool
    may_mutate_trust: Literal[False] = False
    may_suspend_agent: Literal[False] = False
    may_mutate_permissions: Literal[False] = False
    may_grant_authority: Literal[False] = False

    @field_validator("ingested_at")
    @classmethod
    def validate_ingested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("ingested_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.severity is not _severity_for(self.accepted_signals):
            raise ValueError("severity must match accepted Sentinel signals")
        if self.requires_governor_reevaluation != bool(self.accepted_signals):
            raise ValueError("Governor re-evaluation must match accepted Sentinel signals")
        return self


class SentinelEvidenceIngestor:
    """Accept only independently peer-confirmed Sentinel signals as Trust evidence."""

    def ingest(
        self,
        *,
        submission: SentinelEvidenceSubmission,
        attestation: SentinelPeerAttestation,
        ingested_at: datetime,
    ) -> SentinelTrustEvidence:
        if type(submission) is not SentinelEvidenceSubmission:
            raise TypeError("submission must be a canonical SentinelEvidenceSubmission")
        if type(attestation) is not SentinelPeerAttestation:
            raise TypeError("attestation must be a canonical SentinelPeerAttestation")
        if not attestation.independently_auditable:
            raise ValueError("Sentinel peer attestation must be independently auditable")
        peer_id = submission.selected_peer_auditor_agent_id
        if attestation.peer_auditor_agent_id != peer_id:
            raise ValueError("Sentinel attestation must come from the selected peer")
        if (
            attestation.audit_reference != submission.audit_reference
            or attestation.evidence_references != submission.evidence_references
        ):
            raise ValueError("Sentinel attestation must preserve submission provenance")
        if not set(attestation.confirmed_signals).issubset(submission.submitted_signals):
            raise ValueError("peer-confirmed signals must be a subset of submitted signals")
        if (
            attestation.reviewed_at < submission.submitted_at
            or attestation.reviewed_at > ingested_at
        ):
            raise ValueError("Sentinel evidence chronology is invalid")

        return SentinelTrustEvidence(
            target_agent_id=submission.target_agent_id,
            primary_sentinel_agent_id=submission.primary_sentinel_agent_id,
            peer_auditor_agent_id=peer_id,
            audit_reference=submission.audit_reference,
            evidence_references=submission.evidence_references,
            accepted_signals=attestation.confirmed_signals,
            severity=_severity_for(attestation.confirmed_signals),
            submitted_at=submission.submitted_at,
            reviewed_at=attestation.reviewed_at,
            ingested_at=ingested_at,
            requires_governor_reevaluation=bool(attestation.confirmed_signals),
        )


def _severity_for(signals: tuple[SentinelRiskSignal, ...]) -> SentinelEvidenceSeverity:
    critical = {
        SentinelRiskSignal.POLICY_EVASION,
        SentinelRiskSignal.MEMORY_POISONING,
        SentinelRiskSignal.COLLUSION_PATTERN,
    }
    high = {
        SentinelRiskSignal.MISLEADING_RESULT,
        SentinelRiskSignal.SUSPICIOUS_COORDINATION,
        SentinelRiskSignal.EVALUATION_GAMING,
    }
    if critical.intersection(signals):
        return SentinelEvidenceSeverity.CRITICAL
    if high.intersection(signals):
        return SentinelEvidenceSeverity.HIGH
    if signals:
        return SentinelEvidenceSeverity.ELEVATED
    return SentinelEvidenceSeverity.NONE
