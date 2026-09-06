"""Bounded durable audit checkpoints for the Phase 18 Security workflow stage."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.security import (
    SecurityConfirmation,
    SecurityDecision,
    SecurityResult,
    SecuritySeverity,
)
from core.tasks.state_machine import InvalidTaskTransitionError, TaskStateMachine
from core.workflows.deadline import _configure_transaction_timeouts, _is_database_timeout
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.security_errors import (
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    _discard_security_workflow_exception,
)
from core.workflows.security_validation import ValidatedSecurityWorkflowScope
from infrastructure.database.models import AuditEvent, Task
from infrastructure.database.task_status_guard import clear_task_status_authorizations


class SecurityEventType(StrEnum):
    """Closed append-only lifecycle facts for one Security workflow stage."""

    SECURITY_STARTED = "SECURITY_STARTED"
    SECURITY_COMPLETED = "SECURITY_COMPLETED"
    SECURITY_ESCALATED = "SECURITY_ESCALATED"


@dataclass(frozen=True, slots=True)
class _TaskSnapshot:
    status: TaskStatus


def commit_security_started_checkpoint(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    *,
    deadline: float | None = None,
) -> None:
    """Durably claim one Security run while retaining WAITING_SECURITY."""
    failure = _commit_security_checkpoint(
        session,
        scope,
        partial(_stage_security_started, session, scope),
        expected_status=TaskStatus.WAITING_SECURITY,
        deadline=deadline,
    )
    del session, scope, deadline
    if failure is not None:
        _raise_failure(failure)


def commit_security_completed_checkpoint(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    *,
    result: SecurityResult,
    deadline: float | None = None,
) -> None:
    """Atomically persist one Security result and its exact task transition."""
    canonical_result = _canonicalize_result(scope, result)
    failure = _commit_security_checkpoint(
        session,
        scope,
        partial(_stage_security_completed, session, scope, canonical_result),
        expected_status=TaskStatus.WAITING_SECURITY,
        deadline=deadline,
    )
    del canonical_result, result, session, scope, deadline
    if failure is not None:
        _raise_failure(failure)


def commit_security_escalated_checkpoint(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    *,
    error_code: SecurityWorkflowErrorCode,
    deadline: float | None = None,
) -> None:
    """Atomically escalate one started operational failure to human attention."""
    _require_escalation_code(error_code)
    failure = _commit_security_checkpoint(
        session,
        scope,
        partial(_stage_security_escalated, session, scope, error_code),
        expected_status=TaskStatus.WAITING_SECURITY,
        deadline=deadline,
    )
    del error_code, session, scope, deadline
    if failure is not None:
        _raise_failure(failure)


def _stage_security_started(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
) -> None:
    lifecycle_rows = _security_lifecycle_rows(session, scope)
    if _has_unmatched_security_start(lifecycle_rows) or any(
        correlation_id == scope.request.correlation_id for _, correlation_id, _ in lifecycle_rows
    ):
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_STATE)
    request = scope.request.security_request
    _stage_security_event(
        session,
        scope,
        SecurityEventType.SECURITY_STARTED,
        {
            "security_agent_id": scope.security.slug,
            "acceptance_criterion_count": len(request.acceptance_criteria),
            "affected_file_count": len(request.affected_files),
        },
    )


def _stage_security_completed(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    result: SecurityResult,
) -> None:
    _require_matching_start(session, scope)
    target = {
        SecurityDecision.PASS: TaskStatus.COMPLETED,
        SecurityDecision.WARN: TaskStatus.WAITING_HUMAN,
        SecurityDecision.BLOCK: TaskStatus.CHANGES_REQUESTED,
    }[result.decision]
    reason = {
        SecurityDecision.PASS: "Independent Security gate passed.",
        SecurityDecision.WARN: "Independent Security gate requires human review.",
        SecurityDecision.BLOCK: "Independent Security gate blocked completion.",
    }[result.decision]
    TaskStateMachine(session).transition(
        scope.task,
        target,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.security.slug,
        reason=reason,
        correlation_id=scope.request.correlation_id,
    )
    counts = Counter(finding.severity for finding in result.findings)
    _stage_security_event(
        session,
        scope,
        SecurityEventType.SECURITY_COMPLETED,
        {
            "decision": result.decision.value,
            "confidence": result.confidence,
            "info_finding_count": counts[SecuritySeverity.INFO],
            "low_finding_count": counts[SecuritySeverity.LOW],
            "medium_finding_count": counts[SecuritySeverity.MEDIUM],
            "high_finding_count": counts[SecuritySeverity.HIGH],
            "critical_finding_count": counts[SecuritySeverity.CRITICAL],
            "confirmed_blocker_count": sum(
                finding.confirmation is SecurityConfirmation.CONFIRMED
                and finding.severity in {SecuritySeverity.HIGH, SecuritySeverity.CRITICAL}
                for finding in result.findings
            ),
            "scanner_suite_id": result.scanner.suite_id,
            "scanner_complete": result.scanner.complete,
            "scanner_truncated": result.scanner.truncated,
        },
    )


def _stage_security_escalated(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    error_code: SecurityWorkflowErrorCode,
) -> None:
    _require_matching_start(session, scope)
    TaskStateMachine(session).transition(
        scope.task,
        TaskStatus.WAITING_HUMAN,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="Security workflow safely escalated for human attention.",
        metadata={"security_workflow_error_code": error_code.value},
        correlation_id=scope.request.correlation_id,
    )
    _stage_security_event(
        session,
        scope,
        SecurityEventType.SECURITY_ESCALATED,
        {
            "security_agent_id": scope.security.slug,
            "error_code": error_code.value,
        },
    )


def _stage_security_event(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    event_type: SecurityEventType,
    data: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            actor_type=AuditActorType.AGENT,
            actor_id=scope.security.slug,
            project_id=scope.task.project_id,
            task_id=scope.task.id,
            event_type=event_type.value,
            action="record_security_checkpoint",
            resource_type="SECURITY_WORKFLOW",
            resource_id=str(scope.task.id),
            result=AuditResult.SUCCEEDED,
            data=data,
            correlation_id=scope.request.correlation_id,
        )
    )


def _commit_security_checkpoint(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
    stage: Callable[[], None],
    *,
    expected_status: TaskStatus,
    deadline: float | None,
) -> SecurityWorkflowError | None:
    snapshot: _TaskSnapshot | None = None
    connection: Connection | None = None
    task = scope.task
    error_code: SecurityWorkflowErrorCode | None = None
    try:
        connection = session.connection()
        if deadline is not None:
            _configure_transaction_timeouts(session, deadline)
        task = _locked_expected_task(session, scope, expected_status)
        snapshot = _TaskSnapshot(status=task.status)
        stage()
        session.commit()
        return None
    except SecurityWorkflowError as error:
        error_code = error.code
        _discard_security_workflow_exception(error)
        del error
    except InvalidTaskTransitionError as error:
        error_code = SecurityWorkflowErrorCode.CONCURRENT_MODIFICATION
        _discard_security_workflow_exception(error)
        del error
    except WorkflowError as error:
        error_code = (
            SecurityWorkflowErrorCode.TIMEOUT
            if error.code is WorkflowErrorCode.TIMEOUT
            else SecurityWorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_security_workflow_exception(error)
        del error
    except SQLAlchemyError as error:
        error_code = (
            SecurityWorkflowErrorCode.TIMEOUT
            if _is_database_timeout(error)
            else SecurityWorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_security_workflow_exception(error)
        del error
    except Exception as error:
        error_code = SecurityWorkflowErrorCode.INTERNAL_FAILURE
        _discard_security_workflow_exception(error)
        del error
    rollback_failed = _recover_failed_checkpoint(session, connection, task, snapshot)
    if rollback_failed:
        error_code = SecurityWorkflowErrorCode.PERSISTENCE_FAILURE
    assert error_code is not None
    del snapshot, connection, task, stage, expected_status, deadline, scope, session
    return SecurityWorkflowError(error_code)


def _locked_expected_task(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
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
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_SCOPE)
    if task.status is not expected_status or task.assigned_agent_id != scope.developer.id:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.CONCURRENT_MODIFICATION)
    return task


def _security_lifecycle_rows(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
) -> list[tuple[str, object, str | None]]:
    rows = session.execute(
        select(AuditEvent.event_type, AuditEvent.correlation_id, AuditEvent.actor_id).where(
            AuditEvent.task_id == scope.task.id,
            AuditEvent.resource_type == "SECURITY_WORKFLOW",
            AuditEvent.event_type.in_([item.value for item in SecurityEventType]),
        )
    )
    return [(event_type, correlation_id, actor_id) for event_type, correlation_id, actor_id in rows]


def _has_unmatched_security_start(rows: list[tuple[str, object, str | None]]) -> bool:
    starts = Counter(
        correlation_id
        for event_type, correlation_id, _ in rows
        if event_type == SecurityEventType.SECURITY_STARTED.value
    )
    terminals = Counter(
        correlation_id
        for event_type, correlation_id, _ in rows
        if event_type
        in {
            SecurityEventType.SECURITY_COMPLETED.value,
            SecurityEventType.SECURITY_ESCALATED.value,
        }
    )
    return any(count > terminals[correlation_id] for correlation_id, count in starts.items())


def _require_matching_start(
    session: Session,
    scope: ValidatedSecurityWorkflowScope,
) -> None:
    rows = _security_lifecycle_rows(session, scope)
    correlation_id = scope.request.correlation_id
    starts = sum(
        event_type == SecurityEventType.SECURITY_STARTED.value
        and event_correlation_id == correlation_id
        and actor_id == scope.security.slug
        for event_type, event_correlation_id, actor_id in rows
    )
    terminals = sum(
        event_correlation_id == correlation_id
        and event_type
        in {
            SecurityEventType.SECURITY_COMPLETED.value,
            SecurityEventType.SECURITY_ESCALATED.value,
        }
        for event_type, event_correlation_id, _ in rows
    )
    if starts != 1 or terminals != 0:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_STATE)


def _canonicalize_result(
    scope: ValidatedSecurityWorkflowScope,
    result: SecurityResult,
) -> SecurityResult:
    if type(result) is not SecurityResult:
        del scope, result
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_INPUT)
    try:
        canonical = SecurityResult.model_validate(result.model_dump(mode="python", warnings=False))
    except Exception:
        del scope, result
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_INPUT) from None
    if (
        canonical.correlation_id != scope.request.correlation_id
        or canonical.scanner.finding_count != len(canonical.findings)
    ):
        del scope, result, canonical
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_SCOPE)
    del scope, result
    return canonical


def _require_escalation_code(error_code: SecurityWorkflowErrorCode) -> None:
    allowed = frozenset(
        {
            SecurityWorkflowErrorCode.TIMEOUT,
            SecurityWorkflowErrorCode.COLLABORATOR_FAILURE,
            SecurityWorkflowErrorCode.PERSISTENCE_FAILURE,
            SecurityWorkflowErrorCode.INTERNAL_FAILURE,
        }
    )
    if type(error_code) is not SecurityWorkflowErrorCode or error_code not in allowed:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_INPUT)


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
            _discard_security_workflow_exception(error)
            del error
    try:
        clear_task_status_authorizations(session)
    except BaseException as error:
        _discard_security_workflow_exception(error)
        del error
    if snapshot is not None:
        try:
            set_committed_value(task, "status", snapshot.status)
        except BaseException as error:
            _discard_security_workflow_exception(error)
            del error
    return rollback_failed


def _best_effort_rollback(session: Session) -> bool:
    try:
        session.rollback()
    except BaseException as error:
        _discard_security_workflow_exception(error)
        del error
        return True
    return False


def _raise_failure(error: SecurityWorkflowError) -> NoReturn:
    raise error
