"""PostgreSQL integration tests for Phase 16 workflow preflight."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import AgentStatus, TaskStatus
from core.workflows import (
    DeveloperReviewerWorkflowRequest,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowHandoffContext,
    validate_workflow_request,
)
from infrastructure.database.models import AuditEvent, Task
from tests.workflows.factories import handoff_context_values, persisted_workflow_request

pytest_plugins = ("tests.database.conftest",)


def _assert_rejected_without_side_effects(
    session: Session,
    task: Task,
    request: DeveloperReviewerWorkflowRequest,
    expected_code: WorkflowErrorCode,
) -> None:
    """Ensure preflight never assigns, audits, or invokes later workflow stages."""
    original_status = task.status
    original_assigned_agent_id = task.assigned_agent_id
    audit_count = session.scalar(select(func.count()).select_from(AuditEvent))

    with pytest.raises(WorkflowError) as raised:
        validate_workflow_request(session, request)

    assert raised.value.code is expected_code
    assert task.status is original_status
    assert task.assigned_agent_id == original_assigned_agent_id
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_count


def test_validation_returns_a_canonical_persistent_scope(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent later workflow stages from rebuilding scope from untrusted request fields."""
    task, developer, reviewer, request = persisted_workflow_request(db_session, tmp_path)

    validated = validate_workflow_request(db_session, request)

    assert validated.request is not request
    assert validated.task is task
    assert validated.developer is developer
    assert validated.reviewer is reviewer
    assert validated.handoff_context.model_dump(mode="python") == {
        "task_id": str(task.id),
        "project_id": str(task.project_id),
        "task_title": "Correct addition",
        "task_description": "Correct the faulty addition implementation.",
        "acceptance_criteria": ("The existing test suite passes.",),
        "developer_id": "developer-01",
        "reviewer_id": "reviewer-01",
        "reviewer_profile": request.reviewer_profile.model_dump(mode="python"),
        "required_check_profiles": request.developer_request.required_check_profiles,
    }


def test_validation_rejects_a_type_confused_request_before_persistence_side_effects(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent model_copy() corruption from bypassing the public workflow boundary."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    forged = request.model_copy(update={"task_id": "not-a-uuid"})

    _assert_rejected_without_side_effects(db_session, task, forged, WorkflowErrorCode.INVALID_INPUT)


def test_validation_rejects_a_non_exact_top_level_object() -> None:
    """Prevent arbitrary objects from reaching request canonicalization."""
    with pytest.raises(WorkflowError) as raised:
        validate_workflow_request(None, object())  # type: ignore[arg-type]

    assert raised.value.code is WorkflowErrorCode.INVALID_INPUT


def test_validation_preserves_a_preexisting_ready_assignment_on_rejection(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent rejected preflight from clearing a READY task's existing assignment."""
    task, developer, _, request = persisted_workflow_request(
        db_session,
        tmp_path,
        task_overrides={"assigned_agent_id": None},
    )
    task.assigned_agent_id = developer.id
    db_session.flush()
    forged = request.model_copy(update={"task_id": "not-a-uuid"})

    _assert_rejected_without_side_effects(db_session, task, forged, WorkflowErrorCode.INVALID_INPUT)


@pytest.mark.parametrize("missing", ["task", "developer", "reviewer"])
def test_validation_rejects_missing_persistent_scope_before_side_effects(
    db_session: Session, tmp_path: Path, missing: str
) -> None:
    """Prevent nonexistent persistent identities from reaching assignment or collaborators."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    fields = {
        "task": "task_id",
        "developer": "developer_agent_id",
        "reviewer": "reviewer_agent_id",
    }
    forged = request.model_copy(update={fields[missing]: uuid4()})

    _assert_rejected_without_side_effects(db_session, task, forged, WorkflowErrorCode.INVALID_SCOPE)


def test_validation_rejects_a_non_ready_task_before_side_effects(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent workflows from reopening an ineligible persistent task."""
    task, _, _, request = persisted_workflow_request(
        db_session, tmp_path, task_overrides={"status": TaskStatus.BACKLOG}
    )

    _assert_rejected_without_side_effects(
        db_session, task, request, WorkflowErrorCode.INVALID_STATE
    )


@pytest.mark.parametrize("kind", ["persistent_ids", "profile_slugs"])
def test_validation_rejects_non_independent_author_and_reviewer(
    db_session: Session, tmp_path: Path, kind: str
) -> None:
    """Prevent a persistent or declared identity from authoring and reviewing one task."""
    task, developer, _, request = persisted_workflow_request(db_session, tmp_path)
    if kind == "persistent_ids":
        forged = request.model_copy(update={"reviewer_agent_id": developer.id})
    else:
        forged = request.model_copy(
            update={
                "reviewer_profile": request.reviewer_profile.model_copy(
                    update={"id": "developer-01"}
                )
            }
        )

    expected_code = (
        WorkflowErrorCode.INVALID_INPUT
        if kind == "persistent_ids"
        else WorkflowErrorCode.INVALID_SCOPE
    )
    _assert_rejected_without_side_effects(db_session, task, forged, expected_code)


@pytest.mark.parametrize(
    ("agent_kind", "overrides", "expected_code"),
    [
        ("developer", {"role": "Reviewer"}, WorkflowErrorCode.INVALID_ROLE),
        ("reviewer", {"role": "Developer"}, WorkflowErrorCode.INVALID_ROLE),
        ("developer", {"status": AgentStatus.OFFLINE}, WorkflowErrorCode.INVALID_AGENT),
        ("reviewer", {"status": AgentStatus.BLOCKED}, WorkflowErrorCode.INVALID_AGENT),
    ],
)
def test_validation_rejects_ineligible_persistent_agents_before_side_effects(
    db_session: Session,
    tmp_path: Path,
    agent_kind: str,
    overrides: dict[str, object],
    expected_code: WorkflowErrorCode,
) -> None:
    """Prevent invalid persistent role or availability from reaching the workflow."""
    task, _, _, request = persisted_workflow_request(
        db_session,
        tmp_path,
        **{f"{agent_kind}_overrides": overrides},
    )

    _assert_rejected_without_side_effects(db_session, task, request, expected_code)


@pytest.mark.parametrize(
    ("field", "value_factory"),
    [
        (
            "profile",
            lambda request: request.developer_request.profile.model_copy(update={"id": "other"}),
        ),
        (
            "task",
            lambda request: request.developer_request.task.model_copy(update={"task_id": uuid4()}),
        ),
        (
            "execution_context",
            lambda request: request.developer_request.execution_context.model_copy(
                update={"task_id": uuid4()}
            ),
        ),
        (
            "execution_context",
            lambda request: request.developer_request.execution_context.model_copy(
                update={"project_id": uuid4()}
            ),
        ),
        (
            "execution_context",
            lambda request: request.developer_request.execution_context.model_copy(
                update={"agent_id": "other"}
            ),
        ),
        (
            "execution_context",
            lambda request: request.developer_request.execution_context.model_copy(
                update={"correlation_id": uuid4()}
            ),
        ),
    ],
)
def test_validation_rejects_mismatched_developer_runtime_scope_before_side_effects(
    db_session: Session,
    tmp_path: Path,
    field: str,
    value_factory: Callable[[DeveloperReviewerWorkflowRequest], object],
) -> None:
    """Prevent a Developer request from acting outside its persistent task and identity scope."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    developer_request = request.developer_request.model_copy(update={field: value_factory(request)})
    forged = request.model_copy(update={"developer_request": developer_request})

    _assert_rejected_without_side_effects(db_session, task, forged, WorkflowErrorCode.INVALID_SCOPE)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("objective", "Different persistent objective."),
        ("acceptance_criteria", ("Different criterion.",)),
    ],
)
def test_validation_rejects_developer_task_content_mismatch_before_side_effects(
    db_session: Session, tmp_path: Path, field: str, value: object
) -> None:
    """Prevent developer work from using task text other than the persisted task contract."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    runtime_task = request.developer_request.task.model_copy(update={field: value})
    forged = request.model_copy(
        update={
            "developer_request": request.developer_request.model_copy(update={"task": runtime_task})
        }
    )

    _assert_rejected_without_side_effects(db_session, task, forged, WorkflowErrorCode.INVALID_SCOPE)


@pytest.mark.parametrize(
    "task_overrides",
    [
        {"title": ""},
        {"title": "x" * 256},
        {"description": None},
        {"description": ""},
        {"description": "x" * 8193},
        {"acceptance_criteria": []},
        {"acceptance_criteria": ["   "]},
        {"acceptance_criteria": [123]},
        {"acceptance_criteria": ["same", "same"]},
        {"acceptance_criteria": [f"criterion {index}" for index in range(17)]},
    ],
)
def test_validation_rejects_unrepresentable_persistent_task_content_before_side_effects(
    db_session: Session, tmp_path: Path, task_overrides: dict[str, object]
) -> None:
    """Prevent malformed or oversized persisted task data from reaching bounded agents."""
    task, _, _, request = persisted_workflow_request(
        db_session, tmp_path, task_overrides=task_overrides
    )

    _assert_rejected_without_side_effects(
        db_session, task, request, WorkflowErrorCode.INVALID_SCOPE
    )


def test_validation_rejects_an_overlong_persistent_criterion_without_side_effects(
    db_session: Session, tmp_path: Path
) -> None:
    """Prevent persisted criteria outside the 1,024-character handoff bound from reaching agents."""
    task, _, _, request = persisted_workflow_request(
        db_session,
        tmp_path,
        task_overrides={"acceptance_criteria": ["x" * 1025]},
    )

    _assert_rejected_without_side_effects(
        db_session, task, request, WorkflowErrorCode.INVALID_SCOPE
    )


def test_handoff_context_rejects_a_criterion_above_its_persistent_bound() -> None:
    """Prevent a relaxed handoff criterion bound from accepting stored overlong task content."""
    values = handoff_context_values()
    values["acceptance_criteria"] = ["x" * 1025]

    with pytest.raises(ValidationError):
        WorkflowHandoffContext.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "other-reviewer"),
        ("role", "Developer"),
        ("status", AgentStatus.OFFLINE),
    ],
)
def test_validation_rejects_reviewer_profile_mismatch_before_side_effects(
    db_session: Session, tmp_path: Path, field: str, value: object
) -> None:
    """Prevent a Reviewer declaration from diverging from the persistent reviewer identity."""
    task, _, _, request = persisted_workflow_request(db_session, tmp_path)
    forged = request.model_copy(
        update={"reviewer_profile": request.reviewer_profile.model_copy(update={field: value})}
    )

    _assert_rejected_without_side_effects(db_session, task, forged, WorkflowErrorCode.INVALID_SCOPE)
