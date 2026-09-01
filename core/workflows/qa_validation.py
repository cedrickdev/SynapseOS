"""Fail-closed persistent preflight for the Phase 17 QA workflow stage."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.enums import AgentStatus, TaskStatus
from core.qa import QAError, validate_qa_request
from core.workflows.deadline import _configure_transaction_timeouts
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.qa_errors import (
    QAWorkflowError,
    QAWorkflowErrorCode,
    _discard_qa_workflow_exception,
    _raise_qa_workflow_error,
)
from core.workflows.qa_types import QAWorkflowRequest
from infrastructure.database.models import Agent, Task

_ACTIVE_AGENT_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


@dataclass(frozen=True, slots=True)
class ValidatedQAWorkflowScope:
    """Canonical persistent state accepted before any QA collaborator call."""

    request: QAWorkflowRequest
    task: Task
    developer: Agent
    reviewer: Agent
    qa: Agent


def validate_qa_workflow_request(
    session: Session,
    request: QAWorkflowRequest,
) -> ValidatedQAWorkflowScope:
    """Validate one strict workflow request against its WAITING_QA scope."""
    result, error_code = _validate_qa_workflow_request_result(session, request)
    del session, request
    if error_code is not None:
        del result
        _raise_qa_workflow_error(error_code)
    assert result is not None
    return result


def _validate_qa_workflow_request_result(
    session: Session,
    request: QAWorkflowRequest,
    *,
    deadline: float | None = None,
) -> tuple[ValidatedQAWorkflowScope | None, QAWorkflowErrorCode | None]:
    try:
        if type(request) is not QAWorkflowRequest:
            return None, QAWorkflowErrorCode.INVALID_INPUT
        canonical_request = _canonicalize_qa_workflow_request(request)
        if deadline is not None:
            _configure_transaction_timeouts(session, deadline)
        task, developer, reviewer, qa = _load_qa_scope(session, canonical_request)
        _validate_persistent_qa_scope(canonical_request, task, developer, reviewer, qa)
        _validate_nested_qa_request(canonical_request)
        return (
            ValidatedQAWorkflowScope(
                request=canonical_request,
                task=task,
                developer=developer,
                reviewer=reviewer,
                qa=qa,
            ),
            None,
        )
    except QAWorkflowError as error:
        code = error.code
        _discard_qa_workflow_exception(error)
        del error
        return None, code
    except SQLAlchemyError as error:
        _discard_qa_workflow_exception(error)
        del error
        return None, QAWorkflowErrorCode.PERSISTENCE_FAILURE
    except WorkflowError as error:
        code = (
            QAWorkflowErrorCode.TIMEOUT
            if error.code is WorkflowErrorCode.TIMEOUT
            else QAWorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_qa_workflow_exception(error)
        del error
        return None, code
    except Exception as error:
        _discard_qa_workflow_exception(error)
        del error
        return None, QAWorkflowErrorCode.INTERNAL_FAILURE


def _canonicalize_qa_workflow_request(request: QAWorkflowRequest) -> QAWorkflowRequest:
    try:
        return QAWorkflowRequest.model_validate(request.model_dump(mode="python", warnings=False))
    except (TypeError, ValueError, ValidationError):
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_INPUT) from None


def _load_qa_scope(
    session: Session,
    request: QAWorkflowRequest,
) -> tuple[Task, Agent, Agent, Agent]:
    task = session.scalar(select(Task).where(Task.id == request.task_id).with_for_update())
    developer = session.get(Agent, request.developer_agent_id)
    reviewer = session.get(Agent, request.reviewer_agent_id)
    qa = session.get(Agent, request.qa_agent_id)
    if task is None or developer is None or reviewer is None or qa is None:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_SCOPE)
    return task, developer, reviewer, qa


def _validate_persistent_qa_scope(
    request: QAWorkflowRequest,
    task: Task,
    developer: Agent,
    reviewer: Agent,
    qa: Agent,
) -> None:
    if task.status is not TaskStatus.WAITING_QA:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_STATE)
    if len({developer.id, reviewer.id, qa.id}) != 3:
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_SCOPE)
    if developer.role != "Developer" or reviewer.role != "Reviewer" or qa.role != "QA":
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_ROLE)
    if any(agent.status not in _ACTIVE_AGENT_STATUSES for agent in (developer, reviewer, qa)):
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_AGENT)
    nested = request.qa_request
    context = nested.execution_context
    if (
        task.assigned_agent_id != developer.id
        or request.task_id != task.id
        or nested.task_id != task.id
        or nested.project_id != task.project_id
        or nested.developer_id != developer.slug
        or nested.reviewer_id != reviewer.slug
        or nested.qa_id != qa.slug
        or len({developer.slug, reviewer.slug, qa.slug}) != 3
        or nested.profile.id != qa.slug
        or nested.profile.role != qa.role
        or nested.profile.status is not qa.status
        or context.agent_id != qa.slug
        or context.task_id != task.id
        or context.project_id != task.project_id
        or context.correlation_id != request.correlation_id
        or nested.task_title != task.title
        or nested.task_description != task.description
        or nested.acceptance_criteria != tuple(task.acceptance_criteria)
    ):
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_SCOPE)


def _validate_nested_qa_request(request: QAWorkflowRequest) -> None:
    try:
        validate_qa_request(request.qa_request)
    except QAError as error:
        _discard_qa_workflow_exception(error)
        del error
        raise QAWorkflowError(QAWorkflowErrorCode.INVALID_SCOPE) from None
