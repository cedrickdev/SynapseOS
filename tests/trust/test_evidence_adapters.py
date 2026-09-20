"""Tests for deterministic trusted-evidence to Trust-event adaptation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from core.genome import EvidenceOutcome, EvidenceSignal, EvidenceSourceType
from core.trust import TrustEventSeverity, TrustEventType
from infrastructure.database.models import AgentGenomeEvidence
from infrastructure.trust.adapters import TrustEvidenceAdapter


def _evidence(
    *,
    source_type: EvidenceSourceType,
    outcome: EvidenceOutcome,
) -> AgentGenomeEvidence:
    return AgentGenomeEvidence(
        agent_id=uuid.uuid4(),
        source_type=source_type,
        source_id=uuid.uuid4(),
        signal={
            EvidenceSourceType.AGENT_RUN: EvidenceSignal.RUN_OUTCOME,
            EvidenceSourceType.PULL_REQUEST_REVIEW: EvidenceSignal.REVIEW_OUTCOME,
            EvidenceSourceType.QA_APPROVAL: EvidenceSignal.QA_OUTCOME,
            EvidenceSourceType.SECURITY_APPROVAL: EvidenceSignal.SECURITY_OUTCOME,
        }[source_type],
        outcome=outcome,
        metadata_={},
        observed_at=datetime.now(UTC),
    )


def test_adapter_maps_trusted_security_block_to_severe_source_linked_event() -> None:
    evidence = _evidence(
        source_type=EvidenceSourceType.SECURITY_APPROVAL,
        outcome=EvidenceOutcome.BLOCKED,
    )

    draft = TrustEvidenceAdapter.from_genome_evidence(evidence)

    assert draft.agent_id == evidence.agent_id
    assert draft.event_type is TrustEventType.SECURITY_OUTCOME
    assert draft.impact == Decimal("-25.00")
    assert draft.severity is TrustEventSeverity.CRITICAL
    assert draft.source_ref == f"SECURITY_APPROVAL:{evidence.source_id}"


def test_adapter_rejects_usage_and_cancelled_evidence_without_creating_trust_events() -> None:
    usage = AgentGenomeEvidence(
        agent_id=uuid.uuid4(),
        source_type=EvidenceSourceType.USAGE_RECORD,
        source_id=uuid.uuid4(),
        signal=EvidenceSignal.TOTAL_TOKENS,
        outcome=EvidenceOutcome.OBSERVED,
        numeric_value=Decimal("42"),
        unit="TOKENS",
        metadata_={},
        observed_at=datetime.now(UTC),
    )
    cancelled = _evidence(
        source_type=EvidenceSourceType.AGENT_RUN,
        outcome=EvidenceOutcome.CANCELLED,
    )

    assert TrustEvidenceAdapter.from_genome_evidence(usage) is None
    assert TrustEvidenceAdapter.from_genome_evidence(cancelled) is None
