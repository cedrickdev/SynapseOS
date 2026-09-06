"""PostgreSQL tests for append-only Phase 18 Security checkpoints."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.security import SecurityResult
from core.workflows import (
    SecurityEventType,
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    commit_security_completed_checkpoint,
    commit_security_started_checkpoint,
    validate_security_workflow_request,
)
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import AuditEvent
from tests.workflows.security_factories import (
    blocking_security_result,
    passing_security_result,
    persisted_security_workflow_request,
    warning_security_result,
)

pytest_plugins = ("tests.database.conftest",)


def _security_events(session: Session) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.event_type.in_([item.value for item in SecurityEventType]))
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )


def _stage_historical_event(
    session: Session,
    *,
    task_id: object,
    project_id: object,
    actor_id: str,
    event_type: SecurityEventType,
    correlation_id: object,
) -> None:
    session.add(
        AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
            event_type=event_type.value,
            action="record_security_checkpoint",
            resource_type="SECURITY_WORKFLOW",
            resource_id=str(task_id),
            result=AuditResult.SUCCEEDED,
            data={},
            correlation_id=correlation_id,
        )
    )


def test_started_checkpoint_commits_allowlisted_scalars_without_transition(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """A durable start closes SQL work before Security sees source-bearing input."""
    task, _, _, _, security, request = persisted_security_workflow_request(db_session, tmp_path)
    scope = validate_security_workflow_request(db_session, request)

    commit_security_started_checkpoint(db_session, scope)

    assert db_session.in_transaction() is False
    assert task.status is TaskStatus.WAITING_SECURITY
    events = _security_events(db_session)
    assert [event.event_type for event in events] == [SecurityEventType.SECURITY_STARTED.value]
    event = events[0]
    assert event.actor_id == security.slug
    assert event.correlation_id == request.correlation_id
    assert event.data == {
        "acceptance_criterion_count": 1,
        "affected_file_count": 1,
        "security_agent_id": security.slug,
    }


def test_started_checkpoint_rejects_any_unmatched_start_across_correlations(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """A stale durable claim from another correlation prevents duplicate Security work."""
    task, _, _, _, security, request = persisted_security_workflow_request(db_session, tmp_path)
    stale_correlation = uuid4()
    _stage_historical_event(
        db_session,
        task_id=task.id,
        project_id=task.project_id,
        actor_id=security.slug,
        event_type=SecurityEventType.SECURITY_STARTED,
        correlation_id=stale_correlation,
    )
    db_session.commit()
    scope = validate_security_workflow_request(db_session, request)

    with pytest.raises(SecurityWorkflowError) as raised:
        commit_security_started_checkpoint(db_session, scope)

    assert raised.value.code is SecurityWorkflowErrorCode.INVALID_STATE
    assert [event.correlation_id for event in _security_events(db_session)] == [stale_correlation]


def test_started_checkpoint_allows_historical_matched_terminal_pair(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Completed historical attempts do not permanently lock the Security stage."""
    task, _, _, _, security, request = persisted_security_workflow_request(db_session, tmp_path)
    old_correlation = uuid4()
    for event_type in (
        SecurityEventType.SECURITY_STARTED,
        SecurityEventType.SECURITY_ESCALATED,
    ):
        _stage_historical_event(
            db_session,
            task_id=task.id,
            project_id=task.project_id,
            actor_id=security.slug,
            event_type=event_type,
            correlation_id=old_correlation,
        )
    db_session.commit()
    scope = validate_security_workflow_request(db_session, request)

    commit_security_started_checkpoint(db_session, scope)

    assert Counter(event.correlation_id for event in _security_events(db_session)) == Counter(
        {old_correlation: 2, request.correlation_id: 1}
    )


@pytest.mark.parametrize(
    ("result_factory", "expected_status"),
    [
        (passing_security_result, TaskStatus.COMPLETED),
        (warning_security_result, TaskStatus.WAITING_HUMAN),
        (blocking_security_result, TaskStatus.CHANGES_REQUESTED),
    ],
)
def test_completed_checkpoint_atomically_transitions_and_audits_exact_result(
    db_session: Session,
    tmp_path: Path,
    result_factory: Callable[[object], SecurityResult],
    expected_status: TaskStatus,
) -> None:
    """Each Security decision uses its sole state-machine edge and one correlation."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    scope = validate_security_workflow_request(db_session, request)
    commit_security_started_checkpoint(db_session, scope)
    result = result_factory(request.security_request)

    commit_security_completed_checkpoint(db_session, scope, result=result)

    assert task.status is expected_status
    events = list(db_session.scalars(select(AuditEvent).where(AuditEvent.task_id == task.id)))
    assert {event.correlation_id for event in events} == {request.correlation_id}
    completed = next(
        event for event in events if event.event_type == SecurityEventType.SECURITY_COMPLETED.value
    )
    counts = {severity: 0 for severity in ("info", "low", "medium", "high", "critical")}
    for finding in result.findings:
        counts[finding.severity.value.lower()] += 1
    assert completed.data == {
        "confidence": result.confidence,
        "confirmed_blocker_count": sum(
            finding.confirmation.value == "CONFIRMED"
            and finding.severity.value in {"HIGH", "CRITICAL"}
            for finding in result.findings
        ),
        "critical_finding_count": counts["critical"],
        "decision": result.decision.value,
        "high_finding_count": counts["high"],
        "info_finding_count": counts["info"],
        "low_finding_count": counts["low"],
        "medium_finding_count": counts["medium"],
        "scanner_complete": result.scanner.complete,
        "scanner_suite_id": result.scanner.suite_id,
        "scanner_truncated": result.scanner.truncated,
    }


def test_completion_failure_rolls_back_transition_and_terminal_event(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed commit cannot leave completion state without its checkpoint."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    scope = validate_security_workflow_request(db_session, request)
    commit_security_started_checkpoint(db_session, scope)
    original_commit = db_session.commit

    def fail_after_flush() -> None:
        db_session.flush()
        raise SQLAlchemyError("private-database-marker")

    monkeypatch.setattr(db_session, "commit", fail_after_flush)

    with pytest.raises(SecurityWorkflowError) as raised:
        commit_security_completed_checkpoint(
            db_session,
            scope,
            result=passing_security_result(request.security_request),
        )

    assert raised.value.code is SecurityWorkflowErrorCode.PERSISTENCE_FAILURE
    assert task.status is TaskStatus.WAITING_SECURITY
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert [event.event_type for event in _security_events(db_session)] == [
        SecurityEventType.SECURITY_STARTED.value
    ]


def test_security_audit_exact_allowlist_excludes_sensitive_material(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Security history contains scalar counts and IDs, never source or findings."""
    _, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    scope = validate_security_workflow_request(db_session, request)
    result = blocking_security_result(request.security_request)
    commit_security_started_checkpoint(db_session, scope)
    commit_security_completed_checkpoint(db_session, scope, result=result)

    serialized = " ".join(str(event.data) for event in _security_events(db_session))
    forbidden = (
        request.security_request.diff,
        request.security_request.task_description,
        request.security_request.acceptance_criteria[0],
        request.security_request.affected_files[0].path,
        request.security_request.affected_files[0].content,
        request.security_request.qa_result.rationale,
        result.findings[0].explanation,
        result.findings[0].remediation,
        result.findings[0].evidence[0].evidence_id,
        result.rationale,
    )
    assert all(marker not in serialized for marker in forbidden)
    assert all(
        isinstance(value, str | int | float | bool)
        for event in _security_events(db_session)
        for value in event.data.values()
    )


def test_security_events_remain_append_only_after_checkpoint(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Persisted Security lifecycle facts cannot be rewritten."""
    _, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    scope = validate_security_workflow_request(db_session, request)
    commit_security_started_checkpoint(db_session, scope)
    event = _security_events(db_session)[0]
    event.action = "rewritten-security-checkpoint"

    with pytest.raises(AppendOnlyViolationError, match="append-only"):
        db_session.flush()
