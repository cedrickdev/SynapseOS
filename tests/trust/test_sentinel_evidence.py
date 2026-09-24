"""Tests for independent Sentinel evidence ingestion into Trust signals."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.sentinel import SentinelRiskSignal
from core.trust.sentinel_evidence import (
    SentinelEvidenceIngestor,
    SentinelEvidenceSeverity,
    SentinelEvidenceSubmission,
    SentinelPeerAttestation,
)


def _submission(submitted_at: datetime) -> SentinelEvidenceSubmission:
    return SentinelEvidenceSubmission(
        target_agent_id=uuid4(),
        primary_sentinel_agent_id=uuid4(),
        selected_peer_auditor_agent_id=uuid4(),
        evidence_references=("audit://evidence/1", "audit://evidence/2"),
        submitted_signals=(
            SentinelRiskSignal.POLICY_EVASION,
            SentinelRiskSignal.EVALUATION_GAMING,
        ),
        audit_reference="audit://sentinel/submission-1",
        submitted_at=submitted_at,
    )


def test_ingestor_accepts_only_peer_confirmed_sentinel_signals() -> None:
    submitted_at = datetime.now(UTC) - timedelta(minutes=2)
    reviewed_at = submitted_at + timedelta(minutes=1)
    ingested_at = reviewed_at + timedelta(minutes=1)
    submission = _submission(submitted_at)
    attestation = SentinelPeerAttestation(
        peer_auditor_agent_id=submission.selected_peer_auditor_agent_id,
        audit_reference=submission.audit_reference,
        evidence_references=submission.evidence_references,
        confirmed_signals=(SentinelRiskSignal.POLICY_EVASION,),
        independently_auditable=True,
        reviewed_at=reviewed_at,
    )

    result = SentinelEvidenceIngestor().ingest(
        submission=submission,
        attestation=attestation,
        ingested_at=ingested_at,
    )

    assert result.target_agent_id == submission.target_agent_id
    assert result.accepted_signals == (SentinelRiskSignal.POLICY_EVASION,)
    assert result.severity is SentinelEvidenceSeverity.CRITICAL
    assert result.requires_governor_reevaluation is True
    assert result.may_mutate_trust is False
    assert result.may_suspend_agent is False
    assert result.may_mutate_permissions is False


def test_ingestor_rejects_unplanned_or_forged_peer_signals() -> None:
    submitted_at = datetime.now(UTC) - timedelta(minutes=2)
    submission = _submission(submitted_at)
    attestation = SentinelPeerAttestation(
        peer_auditor_agent_id=submission.selected_peer_auditor_agent_id,
        audit_reference=submission.audit_reference,
        evidence_references=submission.evidence_references,
        confirmed_signals=(SentinelRiskSignal.MEMORY_POISONING,),
        independently_auditable=True,
        reviewed_at=submitted_at + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="submitted signals"):
        SentinelEvidenceIngestor().ingest(
            submission=submission,
            attestation=attestation,
            ingested_at=datetime.now(UTC),
        )


def test_ingestor_rejects_missing_independent_peer_or_invalid_chronology() -> None:
    submitted_at = datetime.now(UTC) - timedelta(minutes=1)
    submission = _submission(submitted_at)
    attestation = SentinelPeerAttestation(
        peer_auditor_agent_id=submission.selected_peer_auditor_agent_id,
        audit_reference=submission.audit_reference,
        evidence_references=submission.evidence_references,
        confirmed_signals=(SentinelRiskSignal.EVALUATION_GAMING,),
        independently_auditable=False,
        reviewed_at=submitted_at - timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="independently auditable"):
        SentinelEvidenceIngestor().ingest(
            submission=submission,
            attestation=attestation,
            ingested_at=datetime.now(UTC),
        )


def test_ingestor_preserves_empty_peer_confirmation_without_risk_signal() -> None:
    submitted_at = datetime.now(UTC) - timedelta(minutes=2)
    submission = _submission(submitted_at)
    attestation = SentinelPeerAttestation(
        peer_auditor_agent_id=submission.selected_peer_auditor_agent_id,
        audit_reference=submission.audit_reference,
        evidence_references=submission.evidence_references,
        confirmed_signals=(),
        independently_auditable=True,
        reviewed_at=submitted_at + timedelta(minutes=1),
    )

    result = SentinelEvidenceIngestor().ingest(
        submission=submission,
        attestation=attestation,
        ingested_at=datetime.now(UTC),
    )

    assert result.accepted_signals == ()
    assert result.severity is SentinelEvidenceSeverity.NONE
    assert result.requires_governor_reevaluation is False
