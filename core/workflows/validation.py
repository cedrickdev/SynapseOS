"""Fail-closed persistent preflight for the Phase 16 workflow."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.developer import DeveloperError, validate_developer_request
from core.enums import AgentStatus, TaskStatus
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.types import DeveloperReviewerWorkflowRequest, WorkflowHandoffContext
from infrastructure.database.models import Agent, Task

_ACTIVE_AGENT_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


@dataclass(frozen=True, slots=True)
class ValidatedWorkflowScope:
    """Canonical persistent workflow state accepted before any external work."""

    request: DeveloperReviewerWorkflowRequest
    task: Task
    developer: Agent
    reviewer: Agent
    handoff_context: WorkflowHandoffContext


def validate_workflow_request(
    session: Session, request: DeveloperReviewerWorkflowRequest
) -> ValidatedWorkflowScope:
    """Validate one strict workflow request against its persistent READY scope."""
    if type(request) is not DeveloperReviewerWorkflowRequest:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT)
    canonical_request = _canonicalize_request(request)
    task, developer, reviewer = _load_scope(session, canonical_request)
    _validate_persistent_scope(canonical_request, task, developer, reviewer)
    _validate_developer_request(canonical_request)
    handoff_context = _build_handoff_context(canonical_request, task)
    _validate_developer_task_content(canonical_request, handoff_context)
    return ValidatedWorkflowScope(
        request=canonical_request,
        task=task,
        developer=developer,
        reviewer=reviewer,
        handoff_context=handoff_context,
    )


def _canonicalize_request(
    request: DeveloperReviewerWorkflowRequest,
) -> DeveloperReviewerWorkflowRequest:
    try:
        return DeveloperReviewerWorkflowRequest.model_validate(
            request.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT) from None


def _validate_developer_request(request: DeveloperReviewerWorkflowRequest) -> None:
    try:
        validate_developer_request(request.developer_request)
    except DeveloperError:
        raise WorkflowError(WorkflowErrorCode.INVALID_INPUT) from None


def _load_scope(
    session: Session, request: DeveloperReviewerWorkflowRequest
) -> tuple[Task, Agent, Agent]:
    try:
        task = session.get(Task, request.task_id)
        developer = session.get(Agent, request.developer_agent_id)
        reviewer = session.get(Agent, request.reviewer_agent_id)
    except SQLAlchemyError:
        raise WorkflowError(WorkflowErrorCode.PERSISTENCE_FAILURE) from None
    if task is None or developer is None or reviewer is None:
        raise WorkflowError(WorkflowErrorCode.INVALID_SCOPE)
    return task, developer, reviewer


def _validate_persistent_scope(
    request: DeveloperReviewerWorkflowRequest,
    task: Task,
    developer: Agent,
    reviewer: Agent,
) -> None:
    if task.status is not TaskStatus.READY:
        raise WorkflowError(WorkflowErrorCode.INVALID_STATE)
    if request.developer_agent_id == request.reviewer_agent_id:
        raise WorkflowError(WorkflowErrorCode.INVALID_SCOPE)
    if developer.role != "Developer" or reviewer.role != "Reviewer":
        raise WorkflowError(WorkflowErrorCode.INVALID_ROLE)
    if (
        developer.status not in _ACTIVE_AGENT_STATUSES
        or reviewer.status not in _ACTIVE_AGENT_STATUSES
    ):
        raise WorkflowError(WorkflowErrorCode.INVALID_AGENT)
    developer_request = request.developer_request
    context = developer_request.execution_context
    reviewer_profile = request.reviewer_profile
    if (
        developer_request.profile.id != developer.slug
        or developer_request.profile.role != developer.role
        or developer_request.profile.status is not developer.status
        or reviewer_profile.id != reviewer.slug
        or reviewer_profile.role != reviewer.role
        or reviewer_profile.status is not reviewer.status
        or developer.slug == reviewer.slug
        or developer_request.profile.id == reviewer_profile.id
        or request.task_id != task.id
        or developer_request.task.task_id != task.id
        or context.task_id != task.id
        or context.project_id != task.project_id
        or context.agent_id != developer.slug
        or context.correlation_id != request.correlation_id
    ):
        raise WorkflowError(WorkflowErrorCode.INVALID_SCOPE)


def _build_handoff_context(
    request: DeveloperReviewerWorkflowRequest, task: Task
) -> WorkflowHandoffContext:
    try:
        return WorkflowHandoffContext.model_validate(
            {
                "task_id": str(task.id),
                "project_id": str(task.project_id),
                "task_title": task.title,
                "task_description": task.description,
                "acceptance_criteria": task.acceptance_criteria,
                "developer_id": request.developer_request.profile.id,
                "reviewer_id": request.reviewer_profile.id,
                "reviewer_profile": request.reviewer_profile,
                "required_check_profiles": request.developer_request.required_check_profiles,
            }
        )
    except (TypeError, ValueError, ValidationError):
        raise WorkflowError(WorkflowErrorCode.INVALID_SCOPE) from None


def _validate_developer_task_content(
    request: DeveloperReviewerWorkflowRequest, handoff_context: WorkflowHandoffContext
) -> None:
    runtime_task = request.developer_request.task
    if (
        runtime_task.objective != handoff_context.task_description
        or runtime_task.acceptance_criteria != handoff_context.acceptance_criteria
    ):
        raise WorkflowError(WorkflowErrorCode.INVALID_SCOPE)
