"""Real-PostgreSQL tests for the central immutable audit log."""

import uuid

import pytest
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from infrastructure.audit import AuditLogService, AuditRecord


def test_append_and_filter_complete_audit_events(db_session: Session) -> None:
    correlation_id = uuid.uuid4()
    service = AuditLogService(db_session)
    event = service.append(
        AuditRecord(
            actor_type=AuditActorType.AGENT,
            actor_id="reviewer-01",
            event_type="DECISION_RECORDED",
            action="approve_change",
            resource_type="DECISION",
            resource_id="decision-42",
            result=AuditResult.SUCCEEDED,
            correlation_id=correlation_id,
            metadata={"confidence": "0.8400", "evidence_count": 3},
        )
    )
    db_session.flush()

    assert service.get(event.id) == event
    assert service.search(
        actor_type=AuditActorType.AGENT,
        actor_id="reviewer-01",
        resource_type="DECISION",
        resource_id="decision-42",
        result=AuditResult.SUCCEEDED,
        correlation_id=correlation_id,
    ) == [event]


def test_reconstruct_returns_correlated_history_in_chronological_order(db_session: Session) -> None:
    correlation_id = uuid.uuid4()
    service = AuditLogService(db_session)
    first = service.append(
        AuditRecord(
            actor_type=AuditActorType.SYSTEM,
            actor_id="workflow",
            event_type="DECISION_STARTED",
            action="start",
            result=AuditResult.SUCCEEDED,
            correlation_id=correlation_id,
        )
    )
    second = service.append(
        AuditRecord(
            actor_type=AuditActorType.SYSTEM,
            actor_id="workflow",
            event_type="DECISION_COMPLETED",
            action="complete",
            result=AuditResult.SUCCEEDED,
            correlation_id=correlation_id,
        )
    )
    db_session.flush()

    assert service.reconstruct(correlation_id) == [first, second]


def test_sensitive_metadata_is_rejected_before_persistence(db_session: Session) -> None:
    service = AuditLogService(db_session)
    with pytest.raises(ValueError, match="sensitive audit metadata key"):
        service.append(
            AuditRecord(
                actor_type=AuditActorType.SYSTEM,
                actor_id="runtime",
                event_type="LLM_CALL",
                action="complete",
                result=AuditResult.SUCCEEDED,
                metadata={"prompt": "private client text"},
            )
        )

    assert service.search() == []


def test_standard_audit_service_exposes_no_update_or_delete(db_session: Session) -> None:
    service = AuditLogService(db_session)
    assert not hasattr(service, "update")
    assert not hasattr(service, "delete")
