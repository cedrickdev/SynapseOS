"""PostgreSQL tests for bounded durable Phase 17 QA checkpoints."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import TaskStatus
from core.qa import QARequest, QAResult
from core.workflows import (
    QAEventType,
    QAWorkflowError,
    QAWorkflowErrorCode,
    commit_qa_completed_checkpoint,
    commit_qa_escalated_checkpoint,
    commit_qa_started_checkpoint,
    validate_qa_workflow_request,
)
from infrastructure.database.models import AuditEvent
from tests.workflows.qa_factories import (
    failed_qa_result,
    passed_qa_result,
    persisted_qa_workflow_request,
)

pytest_plugins = ("tests.database.conftest",)


def qa_events(session: Session) -> list[AuditEvent]:
    """Return only Phase 17 checkpoint events in lifecycle order."""
    lifecycle_order = {
        QAEventType.QA_STARTED.value: 0,
        QAEventType.QA_COMPLETED.value: 1,
        QAEventType.QA_ESCALATED.value: 1,
    }
    return list(
        sorted(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type.in_([item.value for item in QAEventType])
                )
            ),
            key=lambda event: lifecycle_order[event.event_type],
        )
    )


def test_started_checkpoint_commits_sanitized_event_without_transition(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Close preflight transaction before external QA while retaining WAITING_QA."""
    task, _, _, qa, request = persisted_qa_workflow_request(db_session, tmp_path)
    scope = validate_qa_workflow_request(db_session, request)

    commit_qa_started_checkpoint(db_session, scope)

    assert task.status is TaskStatus.WAITING_QA
    events = qa_events(db_session)
    assert [event.event_type for event in events] == [QAEventType.QA_STARTED.value]
    event = events[0]
    assert event.actor_id == qa.slug
    assert event.correlation_id == request.correlation_id
    assert event.data == {
        "qa_agent_id": qa.slug,
        "required_test_profile_count": 1,
    }


def test_started_checkpoint_rejects_unmatched_duplicate(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Prevent automatic duplicate QA execution after a durable start claim."""
    _, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    scope = validate_qa_workflow_request(db_session, request)
    commit_qa_started_checkpoint(db_session, scope)

    with pytest.raises(QAWorkflowError) as raised:
        commit_qa_started_checkpoint(db_session, scope)

    assert raised.value.code is QAWorkflowErrorCode.INVALID_STATE
    assert len(qa_events(db_session)) == 1


@pytest.mark.parametrize(
    ("result_factory", "expected_status"),
    [
        (passed_qa_result, TaskStatus.WAITING_SECURITY),
        (failed_qa_result, TaskStatus.CHANGES_REQUESTED),
    ],
)
def test_completed_checkpoint_atomically_transitions_and_audits_result(
    db_session: Session,
    tmp_path: Path,
    result_factory: Callable[[QARequest], QAResult],
    expected_status: TaskStatus,
) -> None:
    """Commit one truthful QA decision and its existing state-machine edge."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    scope = validate_qa_workflow_request(db_session, request)
    commit_qa_started_checkpoint(db_session, scope)
    result = result_factory(request.qa_request)

    commit_qa_completed_checkpoint(db_session, scope, result=result)

    assert task.status is expected_status
    events = qa_events(db_session)
    assert [event.event_type for event in events] == [
        QAEventType.QA_STARTED.value,
        QAEventType.QA_COMPLETED.value,
    ]
    completed = events[-1]
    assert set(completed.data) == {
        "confidence",
        "criterion_count",
        "decision",
        "finding_count",
        "qa_agent_id",
        "recommendation_count",
        "tests",
    }
    assert completed.data["tests"] == [
        {"profile_id": "pytest", "status": "SUCCEEDED"}
    ]


def test_escalation_checkpoint_moves_started_failure_to_human(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Persist only a stable operational category after the stage has started."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    scope = validate_qa_workflow_request(db_session, request)
    commit_qa_started_checkpoint(db_session, scope)

    commit_qa_escalated_checkpoint(
        db_session,
        scope,
        error_code=QAWorkflowErrorCode.COLLABORATOR_FAILURE,
    )

    assert task.status is TaskStatus.WAITING_HUMAN
    event = qa_events(db_session)[-1]
    assert event.event_type == QAEventType.QA_ESCALATED.value
    assert event.data == {
        "error_code": "COLLABORATOR_FAILURE",
        "qa_agent_id": "qa-01",
    }


def test_qa_audit_never_persists_source_or_output_content(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Keep source, criteria, findings, paths, and raw output out of append-only audit."""
    _, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    scope = validate_qa_workflow_request(db_session, request)
    commit_qa_started_checkpoint(db_session, scope)
    commit_qa_completed_checkpoint(
        db_session,
        scope,
        result=failed_qa_result(request.qa_request),
    )

    serialized = " ".join(str(event.data) for event in qa_events(db_session))
    for forbidden in (
        request.qa_request.diff,
        request.qa_request.task_description,
        request.qa_request.acceptance_criteria[0],
        "The calculation returns zero.",
        "src/add.py",
        "1 passed",
    ):
        assert forbidden not in serialized
