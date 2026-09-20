"""Deterministic adapters from vetted Genome evidence to Trust events."""

from __future__ import annotations

from decimal import Decimal

from core.genome import EvidenceOutcome, EvidenceSourceType
from core.trust import TrustEventSeverity, TrustEventType
from infrastructure.database.models import AgentGenomeEvidence, AgentTrustEvent


class TrustEvidenceAdapter:
    """Translate only persisted trusted outcomes; never interpret free-form content."""

    @staticmethod
    def from_genome_evidence(evidence: AgentGenomeEvidence) -> AgentTrustEvent | None:
        if type(evidence) is not AgentGenomeEvidence:
            raise TypeError("Trust evidence must be a persisted Genome evidence record")
        event = _EVENTS.get((evidence.source_type, evidence.outcome))
        if event is None:
            return None
        event_type, impact, severity = event
        return AgentTrustEvent(
            agent_id=evidence.agent_id,
            event_type=event_type,
            impact=impact,
            severity=severity,
            source_ref=f"{evidence.source_type.value}:{evidence.source_id}",
        )


_EVENTS: dict[
    tuple[EvidenceSourceType, EvidenceOutcome],
    tuple[TrustEventType, Decimal, TrustEventSeverity],
] = {
    (EvidenceSourceType.AGENT_RUN, EvidenceOutcome.SUCCEEDED): (
        TrustEventType.TASK_OUTCOME,
        Decimal("10.00"),
        TrustEventSeverity.LOW,
    ),
    (EvidenceSourceType.AGENT_RUN, EvidenceOutcome.FAILED): (
        TrustEventType.TASK_OUTCOME,
        Decimal("-10.00"),
        TrustEventSeverity.MEDIUM,
    ),
    (EvidenceSourceType.AGENT_RUN, EvidenceOutcome.TIMED_OUT): (
        TrustEventType.TASK_OUTCOME,
        Decimal("-15.00"),
        TrustEventSeverity.HIGH,
    ),
    (EvidenceSourceType.PULL_REQUEST_REVIEW, EvidenceOutcome.APPROVED): (
        TrustEventType.REVIEW_OUTCOME,
        Decimal("5.00"),
        TrustEventSeverity.LOW,
    ),
    (EvidenceSourceType.PULL_REQUEST_REVIEW, EvidenceOutcome.CHANGES_REQUESTED): (
        TrustEventType.REVIEW_OUTCOME,
        Decimal("-5.00"),
        TrustEventSeverity.MEDIUM,
    ),
    (EvidenceSourceType.QA_APPROVAL, EvidenceOutcome.PASSED): (
        TrustEventType.QA_OUTCOME,
        Decimal("5.00"),
        TrustEventSeverity.LOW,
    ),
    (EvidenceSourceType.QA_APPROVAL, EvidenceOutcome.REJECTED): (
        TrustEventType.QA_OUTCOME,
        Decimal("-10.00"),
        TrustEventSeverity.HIGH,
    ),
    (EvidenceSourceType.QA_APPROVAL, EvidenceOutcome.BLOCKED): (
        TrustEventType.QA_OUTCOME,
        Decimal("-15.00"),
        TrustEventSeverity.CRITICAL,
    ),
    (EvidenceSourceType.SECURITY_APPROVAL, EvidenceOutcome.PASSED): (
        TrustEventType.SECURITY_OUTCOME,
        Decimal("5.00"),
        TrustEventSeverity.LOW,
    ),
    (EvidenceSourceType.SECURITY_APPROVAL, EvidenceOutcome.REJECTED): (
        TrustEventType.SECURITY_OUTCOME,
        Decimal("-15.00"),
        TrustEventSeverity.HIGH,
    ),
    (EvidenceSourceType.SECURITY_APPROVAL, EvidenceOutcome.BLOCKED): (
        TrustEventType.SECURITY_OUTCOME,
        Decimal("-25.00"),
        TrustEventSeverity.CRITICAL,
    ),
}
