"""Bounded durable audit checkpoints for the Phase 17 QA workflow stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.qa import QADecision, QAResult
from core.tasks.state_machine import InvalidTaskTransitionError, TaskStateMachine
from core.workflows.deadline import _configure_transaction_timeouts, _is_database_timeout
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.qa_errors import (
    QAWorkflowError,
    QAWorkflowErrorCode,
    _discard_qa_workflow_exception,
)
from core.workflows.qa_validation import ValidatedQAWorkflowScope
from infrastructure.database.models import AuditEvent, Task
from infrastructure.database.task_status_guard import clear_task_status_authorizations


class QAEventType(StrEnum):
    """Closed append-only lifecycle facts for one QA workflow stage."""

    QA_STARTED = "QA_STARTED"
    QA_COMPLETED = "QA_COMPLETED"
    QA_ESCALATED = "QA_ESCALATED"


@dataclass(frozen=True, slots=True)
class _TaskSnapshot:
    status: TaskStatus


def commit_qa_started_checkpoint(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    *,
    deadline: float | None = None,
) -> None:
    """Durably claim one QA run while leaving the task in WAITING_QA."""
    failure = _commit_qa_checkpoint(
        session,
        scope,
        partial(_stage_qa_started, session, scope),
        expected_status=TaskStatus.WAITING_QA,
        deadline=deadline,
    )
    del session, scope, deadline
    if failure is not None:
        _raise_failure(failure)


def commit_qa_completed_checkpoint(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    *,
    result: QAResult,
    deadline: float | None = None,
) -> None:
    """Atomically persist one functional QA result and its exact task transition."""
    canonical_result = _canonicalize_result(scope, result)
    failure = _commit_qa_checkpoint(
        session,
        scope,
        partial(_stage_qa_completed, session, scope, canonical_result),
        expected_status=TaskStatus.WAITING_QA,
        deadline=deadline,
    )
    del canonical_result, result, session, scope, deadline
    if failure is not None:
        _raise_failure(failure)


def commit_qa_escalated_checkpoint(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    *,
    error_code: QAWorkflowErrorCode,
    deadline: float | None = None,
) -> None:
    """Atomically escalate one started operational failure to human attention."""
    _require_escalation_code(error_code)
    failure = _commit_qa_checkpoint(
        session,
        scope,
        partial(_stage_qa_escalated, session, scope, error_code),
        expected_status=TaskStatus.WAITING_QA,
        deadline=deadline,
    )
    del error_code, session, scope, deadline
    if failure is not None:
        _raise_failure(failure)


def _stage_qa_started(session: Session, scope: ValidatedQAWorkflowScope) -> None:
    if _has_qa_event(session, scope, QAEventType.QA_STARTED):
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_STATE)
    _stage_qa_event(
        session,
        scope,
        QAEventType.QA_STARTED,
        {
            "qa_agent_id": scope.qa.slug,
            "required_test_profile_count": len(scope.request.qa_request.required_test_profiles),
        },
    )


def _stage_qa_completed(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    result: QAResult,
) -> None:
    _require_matching_start(session, scope)
    target = (
        TaskStatus.WAITING_SECURITY
        if result.decision is QADecision.PASSED
        else TaskStatus.CHANGES_REQUESTED
    )
    reason = (
        "Independent QA passed."
        if result.decision is QADecision.PASSED
        else "Independent QA requested changes."
    )
    TaskStateMachine(session).transition(
        scope.task,
        target,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.qa.slug,
        reason=reason,
        correlation_id=scope.request.correlation_id,
    )
    _stage_qa_event(
        session,
        scope,
        QAEventType.QA_COMPLETED,
        {
            "qa_agent_id": scope.qa.slug,
            "decision": result.decision.value,
            "criterion_count": len(result.criteria),
            "finding_count": len(result.findings),
            "recommendation_count": len(result.recommendations),
            "confidence": result.confidence,
            "tests": [
                {"profile_id": item.profile_id.value, "status": item.status.value}
                for item in result.tests
            ],
        },
    )


def _stage_qa_escalated(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    error_code: QAWorkflowErrorCode,
) -> None:
    _require_matching_start(session, scope)
    TaskStateMachine(session).transition(
        scope.task,
        TaskStatus.WAITING_HUMAN,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="QA workflow safely escalated for human attention.",
        metadata={"qa_workflow_error_code": error_code.value},
        correlation_id=scope.request.correlation_id,
    )
    _stage_qa_event(
        session,
        scope,
        QAEventType.QA_ESCALATED,
        {"qa_agent_id": scope.qa.slug, "error_code": error_code.value},
    )


def _stage_qa_event(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    event_type: QAEventType,
    data: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=scope.qa.slug,
            project_id=scope.task.project_id,
            task_id=scope.task.id,
            event_type=event_type.value,
            action="record_qa_checkpoint",
            resource_type="QA_WORKFLOW",
            resource_id=str(scope.task.id),
            result=AuditResult.SUCCEEDED,
            data=data,
            correlation_id=scope.request.correlation_id,
        )
    )


def _commit_qa_checkpoint(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    stage: Callable[[], None],
    *,
    expected_status: TaskStatus,
    deadline: float | None,
) -> QAWorkflowError | None:
    snapshot: _TaskSnapshot | None = None
    connection: Connection | None = None
    task = scope.task
    error_code: QAWorkflowErrorCode | None = None
    try:
        connection = session.connection()
        if deadline is not None:
            _configure_transaction_timeouts(session, deadline)
        task = _locked_expected_task(session, scope, expected_status)
        snapshot = _TaskSnapshot(status=task.status)
        stage()
        session.commit()
        return None
    except QAWorkflowError as error:
        error_code = error.code
        _discard_qa_workflow_exception(error)
        del error
    except InvalidTaskTransitionError as error:
        error_code = QAWorkflowErrorCode.CONCURRENT_MODIFICATION
        _discard_qa_workflow_exception(error)
        del error
    except WorkflowError as error:
        error_code = (
            QAWorkflowErrorCode.TIMEOUT
            if error.code is WorkflowErrorCode.TIMEOUT
            else QAWorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_qa_workflow_exception(error)
        del error
    except SQLAlchemyError as error:
        error_code = (
            QAWorkflowErrorCode.TIMEOUT
            if _is_database_timeout(error)
            else QAWorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_qa_workflow_exception(error)
        del error
    except Exception as error:
        error_code = QAWorkflowErrorCode.INTERNAL_FAILURE
        _discard_qa_workflow_exception(error)
        del error
    rollback_failed = _recover_failed_checkpoint(session, connection, task, snapshot)
    if rollback_failed:
        error_code = QAWorkflowErrorCode.PERSISTENCE_FAILURE
    assert error_code is not None
    del snapshot, connection, task, stage, expected_status, deadline, scope, session
    return QAWorkflowError(error_code)


def _locked_expected_task(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    expected_status: TaskStatus,
) -> Task:
    with session.no_autoflush:
        task = session.scalar(
            select(Task)
            .where(Task.id == scope.task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if task is None:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_SCOPE)
    if task.status is not expected_status or task.assigned_agent_id != scope.developer.id:
        raise QAWorkflowError(QAWorkflowErrorCode.CONCURRENT_MODIFICATION)
    return task


def _has_qa_event(
    session: Session,
    scope: ValidatedQAWorkflowScope,
    event_type: QAEventType,
) -> bool:
    event_id: UUID | None = session.scalar(
        select(AuditEvent.id)
        .where(
            AuditEvent.task_id == scope.task.id,
            AuditEvent.correlation_id == scope.request.correlation_id,
            AuditEvent.actor_id == scope.qa.slug,
            AuditEvent.event_type == event_type.value,
        )
        .limit(1)
    )
    return event_id is not None


def _require_matching_start(
    session: Session,
    scope: ValidatedQAWorkflowScope,
) -> None:
    has_started = _has_qa_event(session, scope, QAEventType.QA_STARTED)
    has_terminal = any(
        _has_qa_event(session, scope, event_type)
        for event_type in (QAEventType.QA_COMPLETED, QAEventType.QA_ESCALATED)
    )
    if not has_started or has_terminal:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_STATE)


def _canonicalize_result(
    scope: ValidatedQAWorkflowScope,
    result: QAResult,
) -> QAResult:
    if type(result) is not QAResult:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_INPUT)
    try:
        canonical = QAResult.model_validate(result.model_dump(mode="python", warnings=False))
    except Exception:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_INPUT) from None
    if canonical.correlation_id != scope.request.correlation_id:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_SCOPE)
    return canonical


def _require_escalation_code(error_code: QAWorkflowErrorCode) -> None:
    allowed = frozenset(
        {
            QAWorkflowErrorCode.TIMEOUT,
            QAWorkflowErrorCode.COLLABORATOR_FAILURE,
            QAWorkflowErrorCode.PERSISTENCE_FAILURE,
            QAWorkflowErrorCode.INTERNAL_FAILURE,
        }
    )
    if type(error_code) is not QAWorkflowErrorCode or error_code not in allowed:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_INPUT)


def _recover_failed_checkpoint(
    session: Session,
    connection: Connection | None,
    task: Task,
    snapshot: _TaskSnapshot | None,
) -> bool:
    rollback_failed = _best_effort_rollback(session)
    if rollback_failed and connection is not None:
        try:
            connection.invalidate()
        except BaseException as error:
            _discard_qa_workflow_exception(error)
            del error
    try:
        clear_task_status_authorizations(session)
    except BaseException as error:
        _discard_qa_workflow_exception(error)
        del error
    if snapshot is not None:
        try:
            set_committed_value(task, "status", snapshot.status)
        except BaseException as error:
            _discard_qa_workflow_exception(error)
            del error
    return rollback_failed


def _best_effort_rollback(session: Session) -> bool:
    try:
        session.rollback()
    except BaseException as error:
        _discard_qa_workflow_exception(error)
        del error
        return True
    return False


def _raise_failure(error: QAWorkflowError) -> NoReturn:
    raise error
