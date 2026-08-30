"""Bounded durable audit checkpoints for the Phase 16 workflow."""

from __future__ import annotations

import math
from collections.abc import Callable
from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult, TaskStatus
from core.reviewer import ReviewDecision
from core.tasks.state_machine import TaskStateMachine
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.validation import ValidatedWorkflowScope
from infrastructure.database.models import AuditEvent


class WorkflowEventType(StrEnum):
    """Closed append-only workflow facts not represented by task status alone."""

    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    DEVELOPER_HANDOFF_CREATED = "DEVELOPER_HANDOFF_CREATED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    REVIEW_CYCLE_EXHAUSTED = "REVIEW_CYCLE_EXHAUSTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"


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
        if event_type in {
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

    def stage() -> None:
        scope.task.assigned_agent_id = scope.developer.id
        TaskStateMachine(session).transition(
            scope.task,
            TaskStatus.ASSIGNED,
            actor_type=AuditActorType.AGENT,
            actor_id=scope.developer.slug,
            reason="Workflow developer assignment accepted.",
        )
        append_workflow_event(session, scope, WorkflowEventType.WORKFLOW_STARTED)

    _commit_checkpoint(session, stage)


def commit_developer_started_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably mark one bounded Developer cycle as in progress."""

    _require_cycle(scope, cycle)

    def stage() -> None:
        TaskStateMachine(session).transition(
            scope.task,
            TaskStatus.IN_PROGRESS,
            actor_type=AuditActorType.AGENT,
            actor_id=scope.developer.slug,
            reason="Workflow developer cycle started.",
        )

    _commit_checkpoint(session, stage)


def commit_developer_handoff_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably record creation of one safe Reviewer handoff."""
    _require_cycle(scope, cycle)

    def stage() -> None:
        append_workflow_event(
            session,
            scope,
            WorkflowEventType.DEVELOPER_HANDOFF_CREATED,
            cycle=cycle,
        )

    _commit_checkpoint(session, stage)


def commit_developer_completed_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably mark one bounded Developer cycle ready for independent review."""
    _require_cycle(scope, cycle)

    def stage() -> None:
        TaskStateMachine(session).transition(
            scope.task,
            TaskStatus.WAITING_REVIEW,
            actor_type=AuditActorType.AGENT,
            actor_id=scope.developer.slug,
            reason="Workflow developer cycle completed.",
        )

    _commit_checkpoint(session, stage)


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

    def stage() -> None:
        TaskStateMachine(session).transition(
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
            append_workflow_event(
                session,
                scope,
                WorkflowEventType.WORKFLOW_COMPLETED,
                cycle=cycle,
            )

    _commit_checkpoint(session, stage)


def commit_review_cycle_exhausted_checkpoint(
    session: Session,
    scope: ValidatedWorkflowScope,
    *,
    cycle: int,
    max_review_cycles: int,
) -> None:
    """Durably escalate an exhausted review workflow to human attention."""
    _require_cycle(scope, cycle)
    _require_max_review_cycles(scope, max_review_cycles)

    def stage() -> None:
        TaskStateMachine(session).transition(
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

    _commit_checkpoint(session, stage)


def commit_next_review_cycle_checkpoint(
    session: Session, scope: ValidatedWorkflowScope, *, cycle: int
) -> None:
    """Durably start the next bounded Developer cycle after requested changes."""
    _require_cycle(scope, cycle)

    def stage() -> None:
        TaskStateMachine(session).transition(
            scope.task,
            TaskStatus.IN_PROGRESS,
            actor_type=AuditActorType.AGENT,
            actor_id=scope.developer.slug,
            reason="Workflow correction cycle started.",
        )

    _commit_checkpoint(session, stage)


def _commit_checkpoint(session: Session, stage: Callable[[], None]) -> None:
    try:
        stage()
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise WorkflowError(WorkflowErrorCode.PERSISTENCE_FAILURE) from None


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
        return {
            "cycle": _require_cycle(scope, cycle),
            "max_review_cycles": _require_max_review_cycles(scope, max_review_cycles),
        }
    _require_absent(decision, review_score, finding_count, max_review_cycles)
    return {"cycle": _require_cycle(scope, cycle)}


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
