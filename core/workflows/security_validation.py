"""Fail-closed persistent preflight for the Phase 18 Security workflow stage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.agents import AgentProfile
from core.commands import CommandTerminalStatus
from core.enums import AgentStatus, TaskStatus
from core.qa import QADecision
from core.security import (
    SecurityError,
    SecurityErrorCode,
    SecurityRequest,
    validate_security_request,
)
from core.workflows.deadline import _configure_transaction_timeouts
from core.workflows.errors import WorkflowError, WorkflowErrorCode
from core.workflows.pull_request_evidence import matches_persisted_pull_request
from core.workflows.security_errors import (
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    _discard_security_workflow_exception,
    _raise_security_workflow_error,
)
from core.workflows.security_types import (
    SecurityWorkflowRequest,
    _has_exact_security_request_types,
)
from infrastructure.database.models import Agent, Task

_ACTIVE_AGENT_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})


@dataclass(frozen=True, slots=True)
class ValidatedSecurityWorkflowScope:
    """Canonical persistent state accepted before any Security collaborator call."""

    request: SecurityWorkflowRequest
    task: Task
    developer: Agent
    reviewer: Agent
    qa: Agent
    security: Agent


def validate_security_workflow_request(
    session: Session,
    request: SecurityWorkflowRequest,
) -> ValidatedSecurityWorkflowScope:
    """Validate one strict workflow request against its WAITING_SECURITY scope."""
    result, error_code = _validate_security_workflow_request_result(session, request)
    del session, request
    if error_code is not None:
        del result
        _raise_security_workflow_error(error_code)
    assert result is not None
    return result


def _validate_security_workflow_request_result(
    session: Session,
    request: SecurityWorkflowRequest,
    *,
    deadline: float | None = None,
) -> tuple[ValidatedSecurityWorkflowScope | None, SecurityWorkflowErrorCode | None]:
    try:
        _validate_raw_workflow_request(request)
        canonical_request = _canonicalize_security_workflow_request(request)
        if not matches_persisted_pull_request(
            session,
            task_id=canonical_request.task_id,
            correlation_id=canonical_request.correlation_id,
            evidence=canonical_request.pull_request_evidence,
        ):
            raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_INPUT)
        if deadline is not None:
            _configure_transaction_timeouts(session, deadline)
        task, developer, reviewer, qa, security = _load_security_scope(session, canonical_request)
        _validate_persistent_security_scope(
            canonical_request,
            task,
            developer,
            reviewer,
            qa,
            security,
        )
        _validate_successful_qa_evidence(canonical_request.security_request)
        _validate_nested_security_request(canonical_request.security_request)
        return (
            ValidatedSecurityWorkflowScope(
                request=canonical_request,
                task=task,
                developer=developer,
                reviewer=reviewer,
                qa=qa,
                security=security,
            ),
            None,
        )
    except SecurityWorkflowError as error:
        code = error.code
        _discard_security_workflow_exception(error)
        del error
        return None, code
    except SQLAlchemyError as error:
        _discard_security_workflow_exception(error)
        del error
        return None, SecurityWorkflowErrorCode.PERSISTENCE_FAILURE
    except WorkflowError as error:
        code = (
            SecurityWorkflowErrorCode.TIMEOUT
            if error.code is WorkflowErrorCode.TIMEOUT
            else SecurityWorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_security_workflow_exception(error)
        del error
        return None, code
    except Exception as error:
        _discard_security_workflow_exception(error)
        del error
        return None, SecurityWorkflowErrorCode.INTERNAL_FAILURE


def _validate_raw_workflow_request(request: SecurityWorkflowRequest) -> None:
    try:
        nested = request.security_request
        valid = (
            type(request) is SecurityWorkflowRequest
            and _has_exact_security_request_types(nested)
            and type(request.task_id) is UUID
            and type(request.correlation_id) is UUID
            and type(request.developer_agent_id) is UUID
            and type(request.reviewer_agent_id) is UUID
            and type(request.qa_agent_id) is UUID
            and type(request.security_agent_id) is UUID
        )
    except Exception:
        valid = False
    if not valid:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_INPUT)


def _canonicalize_security_workflow_request(
    request: SecurityWorkflowRequest,
) -> SecurityWorkflowRequest:
    try:
        return SecurityWorkflowRequest.model_validate(
            request.model_dump(mode="python", warnings=False)
        )
    except (TypeError, ValueError, ValidationError):
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_INPUT) from None


def _load_security_scope(
    session: Session,
    request: SecurityWorkflowRequest,
) -> tuple[Task, Agent, Agent, Agent, Agent]:
    task = session.scalar(select(Task).where(Task.id == request.task_id))
    developer = session.get(Agent, request.developer_agent_id)
    reviewer = session.get(Agent, request.reviewer_agent_id)
    qa = session.get(Agent, request.qa_agent_id)
    security = session.get(Agent, request.security_agent_id)
    if any(item is None for item in (task, developer, reviewer, qa, security)):
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_SCOPE)
    assert task is not None
    assert developer is not None
    assert reviewer is not None
    assert qa is not None
    assert security is not None
    return task, developer, reviewer, qa, security


def _validate_persistent_security_scope(
    request: SecurityWorkflowRequest,
    task: Task,
    developer: Agent,
    reviewer: Agent,
    qa: Agent,
    security: Agent,
) -> None:
    if task.status is not TaskStatus.WAITING_SECURITY:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_STATE)
    agents = (developer, reviewer, qa, security)
    if len({agent.id for agent in agents}) != 4:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_SCOPE)
    if tuple(agent.role for agent in agents) != ("Developer", "Reviewer", "QA", "Security"):
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_ROLE)
    if any(agent.status not in _ACTIVE_AGENT_STATUSES for agent in agents):
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_AGENT)

    nested = request.security_request
    profile = nested.profile
    context = nested.execution_context
    if (
        task.assigned_agent_id != developer.id
        or request.task_id != task.id
        or nested.task_id != task.id
        or nested.project_id != task.project_id
        or nested.developer_id != developer.slug
        or nested.reviewer_id != reviewer.slug
        or nested.qa_id != qa.slug
        or nested.security_id != security.slug
        or len({agent.slug for agent in agents}) != 4
        or not _profile_matches_persistent_security_agent(profile, security)
        or context.agent_id != security.slug
        or context.task_id != task.id
        or context.project_id != task.project_id
        or context.correlation_id != request.correlation_id
        or nested.task_title != task.title
        or nested.task_description != (task.description or "")
        or nested.acceptance_criteria != tuple(task.acceptance_criteria)
        or not _has_valid_managed_workspace_scope(nested, task.project_id)
    ):
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_SCOPE)


def _profile_matches_persistent_security_agent(
    profile: AgentProfile,
    security: Agent,
) -> bool:
    try:
        canonical_reputation = _canonical_decimal_score(security.reputation_score)
        canonical_reliability = _canonical_decimal_score(security.reliability_score)
        return (
            profile.id == security.slug
            and profile.name == security.name
            and profile.role == security.role
            and profile.department == security.department
            and profile.seniority is security.seniority
            and profile.status is security.status
            and profile.autonomy_level == security.autonomy_level
            and profile.reputation_score == canonical_reputation
            and profile.reliability_score == canonical_reliability
        )
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return False


def _canonical_decimal_score(value: object) -> Decimal:
    score = Decimal(str(value))
    if not score.is_finite():
        raise ValueError("persistent agent score must be finite")
    return score


def _has_valid_managed_workspace_scope(request: SecurityRequest, project_id: object) -> bool:
    try:
        root = request.execution_context.workspace_root
        if (
            not isinstance(root, Path)
            or root.name != str(project_id)
            or root.parent.name != "projects"
            or not root.is_dir()
        ):
            return False
        expected_paths = {item.path for item in request.affected_files}
        for relative in expected_paths:
            candidate = root / relative
            if (
                candidate.is_symlink()
                or candidate.resolve(strict=True) != candidate
                or not candidate.is_file()
            ):
                return False
        old_headers = {line[6:] for line in request.diff.splitlines() if line.startswith("--- a/")}
        new_headers = {line[6:] for line in request.diff.splitlines() if line.startswith("+++ b/")}
        return old_headers == expected_paths == new_headers
    except (OSError, RuntimeError, ValueError):
        return False


def _validate_successful_qa_evidence(request: SecurityRequest) -> None:
    try:
        valid = (
            request.qa_result.decision is QADecision.PASSED
            and request.tests == request.qa_result.tests
            and all(
                test.status is CommandTerminalStatus.SUCCEEDED
                and test.exit_code == 0
                and not test.truncated
                for test in request.tests
            )
        )
    except Exception:
        valid = False
    if not valid:
        raise SecurityWorkflowError(SecurityWorkflowErrorCode.INVALID_SCOPE)


def _validate_nested_security_request(request: SecurityRequest) -> None:
    try:
        validate_security_request(request)
    except SecurityError as error:
        code = {
            SecurityErrorCode.INVALID_INPUT: SecurityWorkflowErrorCode.INVALID_INPUT,
            SecurityErrorCode.INVALID_SCOPE: SecurityWorkflowErrorCode.INVALID_SCOPE,
            SecurityErrorCode.INVALID_ROLE: SecurityWorkflowErrorCode.INVALID_ROLE,
            SecurityErrorCode.INACTIVE_AGENT: SecurityWorkflowErrorCode.INVALID_AGENT,
            SecurityErrorCode.INVALID_PERMISSION: SecurityWorkflowErrorCode.INVALID_AGENT,
            SecurityErrorCode.INVALID_TOOLS: SecurityWorkflowErrorCode.INVALID_AGENT,
        }.get(error.code, SecurityWorkflowErrorCode.INTERNAL_FAILURE)
        _discard_security_workflow_exception(error)
        del error
        raise SecurityWorkflowError(code) from None
