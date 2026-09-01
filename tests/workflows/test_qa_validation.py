"""PostgreSQL integration tests for Phase 17 QA workflow preflight."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import AgentStatus, TaskStatus
from core.workflows import (
    QAWorkflowError,
    QAWorkflowErrorCode,
    QAWorkflowRequest,
    validate_qa_workflow_request,
)
from infrastructure.database.models import AuditEvent, Task
from tests.workflows.qa_factories import persisted_qa_workflow_request

pytest_plugins = ("tests.database.conftest",)


def assert_rejected_without_side_effects(
    session: Session,
    task: Task,
    request: QAWorkflowRequest,
    expected_code: QAWorkflowErrorCode,
) -> None:
    """Ensure persistent QA preflight never transitions or audits the task."""
    original_status = task.status
    original_assignment = task.assigned_agent_id
    audit_count = session.scalar(select(func.count()).select_from(AuditEvent))

    with pytest.raises(QAWorkflowError) as raised:
        validate_qa_workflow_request(session, request)

    assert raised.value.code is expected_code
    assert task.status is original_status
    assert task.assigned_agent_id == original_assignment
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_count


def test_qa_preflight_returns_canonical_persistent_scope(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Return the exact task and independent persistent agents needed by orchestration."""
    task, developer, reviewer, qa, request = persisted_qa_workflow_request(db_session, tmp_path)

    validated = validate_qa_workflow_request(db_session, request)

    assert validated.request is not request
    assert validated.task is task
    assert validated.developer is developer
    assert validated.reviewer is reviewer
    assert validated.qa is qa
    assert validated.request.qa_request.profile.id == qa.slug


@pytest.mark.parametrize("missing", ["task", "developer", "reviewer", "qa"])
def test_qa_preflight_rejects_missing_persistent_scope(
    db_session: Session,
    tmp_path: Path,
    missing: str,
) -> None:
    """Require every persistent role and task before QA can run."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    field = {
        "task": "task_id",
        "developer": "developer_agent_id",
        "reviewer": "reviewer_agent_id",
        "qa": "qa_agent_id",
    }[missing]
    forged = request.model_copy(update={field: uuid4()})

    expected = (
        QAWorkflowErrorCode.INVALID_INPUT
        if missing == "task"
        else QAWorkflowErrorCode.INVALID_SCOPE
    )
    assert_rejected_without_side_effects(db_session, task, forged, expected)


def test_qa_preflight_requires_waiting_qa_and_existing_assignment(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Reject a task outside the exact post-review handoff state."""
    task, _, _, _, request = persisted_qa_workflow_request(
        db_session,
        tmp_path,
        task_overrides={"status": TaskStatus.WAITING_REVIEW},
    )

    assert_rejected_without_side_effects(
        db_session, task, request, QAWorkflowErrorCode.INVALID_STATE
    )


def test_qa_preflight_requires_task_assignment_to_developer(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Preserve authorship while the independent QA role verifies the task."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    task.assigned_agent_id = request.reviewer_agent_id
    db_session.flush()

    assert_rejected_without_side_effects(
        db_session, task, request, QAWorkflowErrorCode.INVALID_SCOPE
    )


@pytest.mark.parametrize(
    ("kind", "overrides", "code"),
    [
        ("developer", {"role": "Reviewer"}, "INVALID_ROLE"),
        ("reviewer", {"role": "Developer"}, "INVALID_ROLE"),
        ("qa", {"role": "Reviewer"}, "INVALID_ROLE"),
        ("developer", {"status": AgentStatus.OFFLINE}, "INVALID_AGENT"),
        ("reviewer", {"status": AgentStatus.BLOCKED}, "INVALID_AGENT"),
        ("qa", {"status": AgentStatus.OFFLINE}, "INVALID_AGENT"),
    ],
)
def test_qa_preflight_rejects_wrong_roles_and_inactive_agents(
    db_session: Session,
    tmp_path: Path,
    kind: str,
    overrides: dict[str, object],
    code: str,
) -> None:
    """Require active persistent Developer, Reviewer, and QA identities."""
    task, _, _, _, request = persisted_qa_workflow_request(
        db_session,
        tmp_path,
        **{f"{kind}_overrides": overrides},
    )

    assert_rejected_without_side_effects(
        db_session,
        task,
        request,
        QAWorkflowErrorCode(code),
    )


@pytest.mark.parametrize("field", ["reviewer_agent_id", "qa_agent_id"])
def test_qa_preflight_requires_distinct_persistent_identities(
    db_session: Session,
    tmp_path: Path,
    field: str,
) -> None:
    """Prevent one persistent agent from acting in two workflow roles."""
    task, developer, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    forged = request.model_copy(update={field: developer.id})

    assert_rejected_without_side_effects(
        db_session, task, forged, QAWorkflowErrorCode.INVALID_INPUT
    )


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        ({"developer_id": "other-developer"}, QAWorkflowErrorCode.INVALID_SCOPE),
        ({"reviewer_id": "other-reviewer"}, QAWorkflowErrorCode.INVALID_SCOPE),
        ({"qa_id": "other-qa"}, QAWorkflowErrorCode.INVALID_SCOPE),
        ({"project_id": uuid4()}, QAWorkflowErrorCode.INVALID_SCOPE),
        ({"task_id": uuid4()}, QAWorkflowErrorCode.INVALID_INPUT),
        ({"correlation_id": uuid4()}, QAWorkflowErrorCode.INVALID_INPUT),
    ],
)
def test_qa_preflight_rejects_nested_identity_and_scope_mismatch(
    db_session: Session,
    tmp_path: Path,
    change: dict[str, object],
    expected_code: QAWorkflowErrorCode,
) -> None:
    """Bind nested QA work to the persisted handoff and correlation scope."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    nested = request.qa_request.model_copy(update=change)
    forged = request.model_copy(update={"qa_request": nested})

    assert_rejected_without_side_effects(db_session, task, forged, expected_code)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "other-qa"),
        ("role", "Reviewer"),
        ("status", AgentStatus.OFFLINE),
    ],
)
def test_qa_preflight_rejects_profile_persistence_mismatch(
    db_session: Session,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Prevent the QA declaration from diverging from its persistent identity."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    profile = request.qa_request.profile.model_copy(update={field: value})
    nested = request.qa_request.model_copy(update={"profile": profile})
    forged = request.model_copy(update={"qa_request": nested})

    assert_rejected_without_side_effects(
        db_session, task, forged, QAWorkflowErrorCode.INVALID_SCOPE
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_title", "Different title"),
        ("task_description", "Different description"),
        ("acceptance_criteria", ("Different criterion",)),
    ],
)
def test_qa_preflight_rejects_persistent_task_content_mismatch(
    db_session: Session,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Use the persisted task contract as the source of truth for QA."""
    task, _, _, _, request = persisted_qa_workflow_request(db_session, tmp_path)
    nested = request.qa_request.model_copy(update={field: value})
    forged = request.model_copy(update={"qa_request": nested})

    assert_rejected_without_side_effects(
        db_session, task, forged, QAWorkflowErrorCode.INVALID_SCOPE
    )
