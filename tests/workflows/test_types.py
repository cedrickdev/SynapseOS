"""Behavioral tests for immutable Phase 16 workflow contracts."""

from __future__ import annotations

import math
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.enums import TaskStatus
from core.reviewer import ReviewDecision
from core.workflows import (
    DeveloperReviewerWorkflowRequest,
    DeveloperReviewerWorkflowResult,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowHandoffContext,
    WorkflowOutcome,
)
from tests.workflows.factories import (
    approved_reviewer_result,
    completed_developer_report,
    handoff_context_values,
    workflow_request_values,
)


def test_request_retains_persistent_scope_as_a_frozen_bounded_value(tmp_path: Path) -> None:
    """Prevent a caller from mutating accepted workflow scope or collections."""
    values = workflow_request_values(tmp_path)

    request = DeveloperReviewerWorkflowRequest.model_validate(values)

    assert isinstance(request.task_id, UUID)
    assert request.max_review_cycles == 2
    assert request.timeout_seconds == 30.0
    with pytest.raises(ValidationError):
        request.max_review_cycles = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowRequest.model_validate({**values, "unknown": "value"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_review_cycles", 0),
        ("max_review_cycles", 11),
        ("timeout_seconds", 0.0),
        ("timeout_seconds", 3600.1),
        ("timeout_seconds", math.inf),
    ],
)
def test_request_rejects_cycle_and_timeout_values_outside_workflow_bounds(
    tmp_path: Path, field: str, value: object
) -> None:
    """Prevent unbounded or non-finite workflow execution limits."""
    values = workflow_request_values(tmp_path)
    values[field] = value

    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowRequest.model_validate(values)


def test_request_public_validation_rejects_a_type_confused_model_copy(tmp_path: Path) -> None:
    """Prevent model_copy() from bypassing the public workflow input boundary."""
    request = DeveloperReviewerWorkflowRequest.model_validate(workflow_request_values(tmp_path))
    forged = request.model_copy(update={"task_id": "not-a-uuid"})

    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowRequest.model_validate(forged)


def test_handoff_context_copies_collections_and_requires_canonical_uuid_text() -> None:
    """Prevent later handoff construction from retaining mutable or ambiguous scope data."""
    values = handoff_context_values()
    criteria = values["acceptance_criteria"]
    profiles = values["required_check_profiles"]
    assert isinstance(criteria, list)
    assert isinstance(profiles, list)

    context = WorkflowHandoffContext.model_validate(values)
    criteria.append("A regression test is added.")
    profiles.append(profiles[0])

    assert context.acceptance_criteria == ("The existing test suite passes.",)
    assert len(context.required_check_profiles) == 1
    with pytest.raises(ValidationError):
        WorkflowHandoffContext.model_validate({**values, "task_id": str(uuid4()).upper()})


@pytest.mark.parametrize(
    ("task_status", "outcome"),
    [
        (TaskStatus.WAITING_QA, WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED),
        (TaskStatus.WAITING_HUMAN, WorkflowOutcome.APPROVED),
        (TaskStatus.COMPLETED, WorkflowOutcome.APPROVED),
    ],
)
def test_result_rejects_untruthful_terminal_status_and_outcome_pairs(
    task_status: TaskStatus, outcome: WorkflowOutcome
) -> None:
    """Prevent the workflow from reporting an outcome inconsistent with its terminal task state."""
    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowResult(
            task_status=task_status,
            outcome=outcome,
            developer_cycles=1,
            reviewer_cycles=1,
            developer_report=completed_developer_report(),
            reviewer_result=approved_reviewer_result(),
            correlation_id=uuid4(),
        )


@pytest.mark.parametrize(("developer_cycles", "reviewer_cycles"), [(0, 0), (1, 2), (2, 1)])
def test_result_requires_equal_nonzero_completed_agent_cycles(
    developer_cycles: int, reviewer_cycles: int
) -> None:
    """Prevent a result from concealing a skipped or unmatched agent invocation."""
    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowResult(
            task_status=TaskStatus.WAITING_QA,
            outcome=WorkflowOutcome.APPROVED,
            developer_cycles=developer_cycles,
            reviewer_cycles=reviewer_cycles,
            developer_report=completed_developer_report(),
            reviewer_result=approved_reviewer_result(),
            correlation_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("task_status", "outcome", "reviewer_result"),
    [
        (TaskStatus.WAITING_QA, WorkflowOutcome.APPROVED, "changes_requested"),
        (TaskStatus.WAITING_HUMAN, WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED, "approved"),
    ],
)
def test_result_requires_its_final_reviewer_decision_to_match_its_outcome(
    task_status: TaskStatus, outcome: WorkflowOutcome, reviewer_result: str
) -> None:
    """Prevent terminal workflow metadata from contradicting the final Reviewer decision."""
    final_reviewer_result = approved_reviewer_result().model_copy(
        update={
            "decision": (
                ReviewDecision.CHANGES_REQUESTED
                if reviewer_result == "changes_requested"
                else ReviewDecision.APPROVED
            )
        }
    )

    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowResult(
            task_status=task_status,
            outcome=outcome,
            developer_cycles=1,
            reviewer_cycles=1,
            developer_report=completed_developer_report(),
            reviewer_result=final_reviewer_result,
            correlation_id=uuid4(),
        )


def test_result_retains_only_final_reports_and_scalar_metadata() -> None:
    """Prevent the workflow result from retaining runtime history or all cycle evidence."""
    result = DeveloperReviewerWorkflowResult(
        task_status=TaskStatus.WAITING_QA,
        outcome=WorkflowOutcome.APPROVED,
        developer_cycles=1,
        reviewer_cycles=1,
        developer_report=completed_developer_report(),
        reviewer_result=approved_reviewer_result(),
        correlation_id=uuid4(),
    )

    assert set(result.model_dump()) == {
        "task_status",
        "outcome",
        "developer_cycles",
        "reviewer_cycles",
        "developer_report",
        "reviewer_result",
        "correlation_id",
    }
    assert result.reviewer_result.decision is ReviewDecision.APPROVED


def test_error_exposes_only_an_application_owned_safe_message() -> None:
    """Prevent sensitive collaborator or persistence text from crossing the workflow boundary."""
    sensitive_text = "postgres://workflow:super-secret@db.internal/tasks"

    error = WorkflowError(WorkflowErrorCode.PERSISTENCE_FAILURE)

    assert error.code is WorkflowErrorCode.PERSISTENCE_FAILURE
    assert error.safe_message == "Workflow persistence failed."
    assert str(error) == "Workflow persistence failed."
    assert sensitive_text not in str(error)
    with pytest.raises(TypeError):
        WorkflowError(WorkflowErrorCode.PERSISTENCE_FAILURE, sensitive_text)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        WorkflowError("PERSISTENCE_FAILURE")  # type: ignore[arg-type]
