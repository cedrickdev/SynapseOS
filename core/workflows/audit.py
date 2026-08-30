"""Bounded durable audit checkpoints for the Phase 16 workflow."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from traceback import clear_frames
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.reviewer import ReviewDecision
from core.tasks.state_machine import InvalidTaskTransitionError, TaskStateMachine
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.validation import ValidatedWorkflowScope
from infrastructure.database.models import AuditEvent, Task
from infrastructure.database.task_status_guard import clear_task_status_authorizations


class WorkflowEventType(StrEnum):
    """Closed append-only workflow facts not represented by task status alone."""

    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    DEVELOPER_HANDOFF_CREATED = "DEVELOPER_HANDOFF_CREATED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    REVIEW_CYCLE_EXHAUSTED = "REVIEW_CYCLE_EXHAUSTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"


@dataclass(frozen=True)
class _TaskSnapshot:
    """The only mutable task fields a checkpoint may stage before committing."""

    status: TaskStatus
    assigned_agent_id: UUID | None


def append_workflow_event(
    session: Session,
    scope: ValidatedWorkflowScope,
    event_type: WorkflowEventType,
    *,
    cycle: int | None = None,
    decision: ReviewDecision | None = None,
    review_score: float | None = None,
    finding_count: int | None = None,
    max_review_cycles: int | None = None,
) -> AuditEvent:
    """Stage one workflow fact with only its explicitly approved scalar data."""
    _require_scope(scope)
    _require_event_type(event_type)
    data = _event_data(
        scope,
        event_type,
        cycle=cycle,
        decision=decision,
        review_score=review_score,
        finding_count=finding_count,
        max_review_cycles=max_review_cycles,
    )
    actor_id = (
        scope.developer.slug
        if event_type
        in {
            WorkflowEventType.WORKFLOW_STARTED,
            WorkflowEventType.DEVELOPER_HANDOFF_CREATED,
        }
        else scope.reviewer.slug
    )
    event = AuditEvent(
        actor_type=AuditActorType.AGENT,
        actor_id=actor_id,
        project_id=scope.task.project_id,
        task_id=scope.task.id,
        event_type=event_type.value,
        action="record_workflow_checkpoint",
        resource_type="DEVELOPER_REVIEWER_WORKFLOW",
        resource_id=str(scope.task.id),
        result=AuditResult.SUCCEEDED,
        data=data,
        correlation_id=scope.request.correlation_id,
    )
    session.add(event)
    return event


def commit_assignment_checkpoint(session: Session, scope: ValidatedWorkflowScope) -> None:
    """Durably assign the Developer and record the workflow start as one checkpoint."""
    stage = partial(_stage_assignment, session, scope)
    preflight = partial(_locked_ready_task, session, scope)
    failure = _commit_checkpoint(session, scope.task, stage, preflight=preflight)
    del preflight
    del stage
    del scope
    del session
    if failure is not None:
        _raise_failure(failure)


def commit_developer_started_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably mark one bounded Developer cycle as in progress."""
    stage = partial(_stage_developer_started, session, scope, cycle)
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del cycle
    if failure is not None:
        _raise_failure(failure)


def commit_developer_handoff_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably record creation of one safe Reviewer handoff."""
    stage = partial(_stage_developer_handoff, session, scope, cycle)
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del cycle
    if failure is not None:
        _raise_failure(failure)


def commit_developer_completed_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably mark one bounded Developer cycle ready for independent review."""
    stage = partial(_stage_developer_completed, session, scope, cycle)
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del cycle
    if failure is not None:
        _raise_failure(failure)


def commit_review_completed_checkpoint(
    session: Session,
    scope: ValidatedWorkflowScope,
    *,
    cycle: int,
    decision: ReviewDecision,
    review_score: float,
    finding_count: int,
) -> None:
    """Durably record one Reviewer decision and its exact next task state."""
    stage = partial(
        _stage_review_completed,
        session,
        scope,
        cycle,
        decision,
        review_score,
        finding_count,
    )
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del cycle
    del decision
    del review_score
    del finding_count
    if failure is not None:
        _raise_failure(failure)


def commit_review_cycle_exhausted_checkpoint(
    session: Session,
    scope: ValidatedWorkflowScope,
    *,
    cycle: int,
    max_review_cycles: int,
) -> None:
    """Durably escalate an exhausted review workflow to human attention."""
    stage = partial(_stage_review_cycle_exhausted, session, scope, cycle, max_review_cycles)
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del cycle
    del max_review_cycles
    if failure is not None:
        _raise_failure(failure)


def commit_next_review_cycle_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably start the next bounded Developer cycle after requested changes."""
    stage = partial(_stage_next_review_cycle, session, scope, cycle)
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del cycle
    if failure is not None:
        _raise_failure(failure)


def commit_safe_failure_checkpoint(
    session: Session,
    scope: ValidatedWorkflowScope,
    *,
    error_code: WorkflowErrorCode,
) -> None:
    """Durably escalate one started workflow failure using only its stable category."""
    stage = partial(_stage_safe_failure, session, scope, error_code)
    failure = _commit_checkpoint(session, scope.task, stage)
    del stage
    del scope
    del session
    del error_code
    if failure is not None:
        _raise_failure(failure)


def _stage_assignment(session: Session, scope: ValidatedWorkflowScope) -> None:
    scope.task.assigned_agent_id = scope.developer.id
    _transition(
        session,
        scope,
        scope.task,
        TaskStatus.ASSIGNED,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.developer.slug,
        reason="Workflow developer assignment accepted.",
    )
    append_workflow_event(session, scope, WorkflowEventType.WORKFLOW_STARTED)


def _stage_developer_started(session: Session, scope: ValidatedWorkflowScope, cycle: int) -> None:
    _require_cycle(scope, cycle)
    _transition(
        session,
        scope,
        scope.task,
        TaskStatus.IN_PROGRESS,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.developer.slug,
        reason="Workflow developer cycle started.",
    )


def _stage_developer_handoff(session: Session, scope: ValidatedWorkflowScope, cycle: int) -> None:
    _require_cycle(scope, cycle)
    append_workflow_event(session, scope, WorkflowEventType.DEVELOPER_HANDOFF_CREATED, cycle=cycle)


def _stage_developer_completed(session: Session, scope: ValidatedWorkflowScope, cycle: int) -> None:
    _require_cycle(scope, cycle)
    _transition(
        session,
        scope,
        scope.task,
        TaskStatus.WAITING_REVIEW,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.developer.slug,
        reason="Workflow developer cycle completed.",
    )


def _stage_review_completed(
    session: Session,
    scope: ValidatedWorkflowScope,
    cycle: int,
    decision: ReviewDecision,
    review_score: float,
    finding_count: int,
) -> None:
    _require_cycle(scope, cycle)
    _require_review_decision(decision)
    _require_review_score(review_score)
    _require_finding_count(finding_count)
    target = (
        TaskStatus.WAITING_QA
        if decision is ReviewDecision.APPROVED
        else TaskStatus.CHANGES_REQUESTED
    )
    reason = (
        "Workflow review approved."
        if decision is ReviewDecision.APPROVED
        else "Workflow review requested changes."
    )
    _transition(
        session,
        scope,
        scope.task,
        target,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.reviewer.slug,
        reason=reason,
    )
    append_workflow_event(
        session,
        scope,
        WorkflowEventType.REVIEW_COMPLETED,
        cycle=cycle,
        decision=decision,
        review_score=review_score,
        finding_count=finding_count,
    )
    if decision is ReviewDecision.APPROVED:
        append_workflow_event(session, scope, WorkflowEventType.WORKFLOW_COMPLETED, cycle=cycle)


def _stage_review_cycle_exhausted(
    session: Session, scope: ValidatedWorkflowScope, cycle: int, max_review_cycles: int
) -> None:
    _require_cycle(scope, cycle)
    _require_max_review_cycles(scope, max_review_cycles)
    if cycle != max_review_cycles:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    _transition(
        session,
        scope,
        scope.task,
        TaskStatus.WAITING_HUMAN,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.reviewer.slug,
        reason="Workflow review cycles exhausted.",
    )
    append_workflow_event(
        session,
        scope,
        WorkflowEventType.REVIEW_CYCLE_EXHAUSTED,
        cycle=cycle,
        max_review_cycles=max_review_cycles,
    )


def _stage_next_review_cycle(session: Session, scope: ValidatedWorkflowScope, cycle: int) -> None:
    _require_cycle(scope, cycle)
    _transition(
        session,
        scope,
        scope.task,
        TaskStatus.IN_PROGRESS,
        actor_type=AuditActorType.AGENT,
        actor_id=scope.developer.slug,
        reason="Workflow correction cycle started.",
    )


def _stage_safe_failure(
    session: Session, scope: ValidatedWorkflowScope, error_code: WorkflowErrorCode
) -> None:
    _require_safe_failure_code(error_code)
    _transition(
        session,
        scope,
        scope.task,
        TaskStatus.WAITING_HUMAN,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        reason="Workflow safely escalated for human attention.",
        metadata={"workflow_error_code": error_code.value},
    )


def _commit_checkpoint(
    session: Session,
    task: Task,
    stage: Callable[[], None],
    *,
    preflight: Callable[[], Task] | None = None,
) -> WorkflowError | None:
    snapshot: _TaskSnapshot | None = None
    error_code: WorkflowErrorCode | None = None
    try:
        if preflight is not None:
            task = preflight()
        snapshot = _TaskSnapshot(status=task.status, assigned_agent_id=task.assigned_agent_id)
        stage()
        session.commit()
        return None
    except WorkflowError as error:
        error_code = error.code
        _discard_exception(error)
        del error
    except InvalidTaskTransitionError as error:
        error_code = WorkflowErrorCode.INVALID_STATE
        _discard_exception(error)
        del error
    except SQLAlchemyError as error:
        error_code = WorkflowErrorCode.PERSISTENCE_FAILURE
        _discard_exception(error)
        del error
    except Exception as error:
        error_code = WorkflowErrorCode.INTERNAL_FAILURE
        _discard_exception(error)
        del error
    rollback_failed = _recover_failed_checkpoint(session, task, snapshot)
    if rollback_failed:
        error_code = WorkflowErrorCode.PERSISTENCE_FAILURE
    assert error_code is not None
    del snapshot
    del preflight
    del task
    del stage
    del session
    return WorkflowError(error_code)


def _raise_failure(error: WorkflowError) -> NoReturn:
    """Raise a previously detached public error from a scope-free frame."""
    raise error


def _locked_ready_task(session: Session, scope: ValidatedWorkflowScope) -> Task:
    task = session.scalar(
        select(Task)
        .where(Task.id == scope.task.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise WorkflowError(WorkflowErrorCode.INVALID_SCOPE)
    if task.status is not TaskStatus.READY or task.assigned_agent_id is not None:
        raise WorkflowError(WorkflowErrorCode.INVALID_STATE)
    return task


def _transition(
    session: Session,
    scope: ValidatedWorkflowScope,
    task: Task,
    target: TaskStatus,
    *,
    actor_type: AuditActorType,
    actor_id: str | None,
    reason: str,
    metadata: dict[str, object] | None = None,
) -> AuditEvent:
    return TaskStateMachine(session).transition(
        task,
        target,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        metadata=metadata,
        correlation_id=scope.request.correlation_id,
    )


def _recover_failed_checkpoint(
    session: Session, task: Task, snapshot: _TaskSnapshot | None
) -> bool:
    rollback_failed = _best_effort_rollback(session)
    if rollback_failed:
        _best_effort_invalidate(session)
    _best_effort_clear_authorizations(session)
    if snapshot is not None:
        _restore_task_snapshot(task, snapshot)
    return rollback_failed


def _best_effort_rollback(session: Session) -> bool:
    try:
        session.rollback()
    except BaseException as error:
        _discard_exception(error)
        del error
        return True
    return False


def _best_effort_invalidate(session: Session) -> None:
    try:
        session.invalidate()
    except BaseException as error:
        _discard_exception(error)
        del error


def _best_effort_clear_authorizations(session: Session) -> None:
    try:
        clear_task_status_authorizations(session)
    except BaseException as error:
        _discard_exception(error)
        del error


def _restore_task_snapshot(task: Task, snapshot: _TaskSnapshot) -> None:
    try:
        set_committed_value(task, "status", snapshot.status)
        set_committed_value(task, "assigned_agent_id", snapshot.assigned_agent_id)
    except BaseException as error:
        _discard_exception(error)
        del error


def _discard_exception(error: BaseException) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback = current.__traceback__
        cause = current.__cause__
        context = current.__context__
        current.__traceback__ = None
        current.__cause__ = None
        current.__context__ = None
        if traceback is not None:
            clear_frames(traceback)
        if cause is not None:
            pending.append(cause)
        if context is not None:
            pending.append(context)


def _event_data(
    scope: ValidatedWorkflowScope,
    event_type: WorkflowEventType,
    *,
    cycle: int | None,
    decision: ReviewDecision | None,
    review_score: float | None,
    finding_count: int | None,
    max_review_cycles: int | None,
) -> dict[str, object]:
    if event_type is WorkflowEventType.WORKFLOW_STARTED:
        _require_absent(cycle, decision, review_score, finding_count, max_review_cycles)
        return {
            "developer_agent_id": scope.developer.slug,
            "reviewer_agent_id": scope.reviewer.slug,
            "max_review_cycles": scope.request.max_review_cycles,
        }
    if event_type is WorkflowEventType.DEVELOPER_HANDOFF_CREATED:
        _require_absent(decision, review_score, finding_count, max_review_cycles)
        return {"cycle": _require_cycle(scope, cycle)}
    if event_type is WorkflowEventType.REVIEW_COMPLETED:
        _require_absent(max_review_cycles)
        return {
            "cycle": _require_cycle(scope, cycle),
            "decision": _require_review_decision(decision).value,
            "review_score": _require_review_score(review_score),
            "finding_count": _require_finding_count(finding_count),
        }
    if event_type is WorkflowEventType.REVIEW_CYCLE_EXHAUSTED:
        _require_absent(decision, review_score, finding_count)
        validated_cycle = _require_cycle(scope, cycle)
        validated_max_review_cycles = _require_max_review_cycles(scope, max_review_cycles)
        if validated_cycle != validated_max_review_cycles:
            raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
        return {
            "cycle": validated_cycle,
            "max_review_cycles": validated_max_review_cycles,
        }
    _require_absent(decision, review_score, finding_count, max_review_cycles)
    return {"cycle": _require_cycle(scope, cycle)}


def _require_safe_failure_code(error_code: WorkflowErrorCode) -> None:
    allowed_codes = frozenset(
        {
            WorkflowErrorCode.UNSAFE_HANDOFF,
            WorkflowErrorCode.TIMEOUT,
            WorkflowErrorCode.COLLABORATOR_FAILURE,
            WorkflowErrorCode.PERSISTENCE_FAILURE,
            WorkflowErrorCode.INTERNAL_FAILURE,
        }
    )
    if type(error_code) is not WorkflowErrorCode or error_code not in allowed_codes:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)


def _require_scope(scope: ValidatedWorkflowScope) -> None:
    if type(scope) is not ValidatedWorkflowScope:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)


def _require_event_type(event_type: WorkflowEventType) -> None:
    if type(event_type) is not WorkflowEventType:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)


def _require_cycle(scope: ValidatedWorkflowScope, cycle: int | None) -> int:
    if type(cycle) is not int or not 1 <= cycle <= scope.request.max_review_cycles:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    return cycle


def _require_review_decision(decision: ReviewDecision | None) -> ReviewDecision:
    if type(decision) is not ReviewDecision or decision not in {
        ReviewDecision.APPROVED,
        ReviewDecision.CHANGES_REQUESTED,
    }:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    return decision


def _require_review_score(review_score: float | None) -> float:
    if (
        type(review_score) is not float
        or not math.isfinite(review_score)
        or not 0.0 <= review_score <= 1.0
    ):
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    return review_score


def _require_finding_count(finding_count: int | None) -> int:
    if type(finding_count) is not int or finding_count < 0 or finding_count > 128:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    return finding_count


def _require_max_review_cycles(scope: ValidatedWorkflowScope, value: int | None) -> int:
    if type(value) is not int or value != scope.request.max_review_cycles:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    return value


def _require_absent(*values: object | None) -> None:
    if any(value is not None for value in values):
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
