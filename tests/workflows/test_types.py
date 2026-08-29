"""Behavioral tests for immutable Phase 16 workflow contracts."""

from __future__ import annotations

import math
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.agents import AgentProfile, AgentReportOutcome
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


def test_request_rejects_equal_persistent_developer_and_reviewer_agent_ids(tmp_path: Path) -> None:
    """Prevent a single persistent agent from being assigned to author and review one task."""
    values = workflow_request_values(tmp_path)
    values["reviewer_agent_id"] = values["developer_agent_id"]

    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowRequest.model_validate(values)


def test_request_revalidates_forged_nested_developer_request_and_reviewer_profile(
    tmp_path: Path,
) -> None:
    """Prevent model_copy() corruption from surviving the public workflow request boundary."""
    request = DeveloperReviewerWorkflowRequest.model_validate(workflow_request_values(tmp_path))
    forged_developer_request = request.developer_request.model_copy(
        update={"required_check_profiles": ("unbounded-profile",)}
    )
    forged_reviewer_profile = request.reviewer_profile.model_copy(update={"autonomy_level": 6})

    with pytest.raises(ValidationError) as error:
        DeveloperReviewerWorkflowRequest.model_validate(
            request.model_copy(
                update={
                    "developer_request": forged_developer_request,
                    "reviewer_profile": forged_reviewer_profile,
                }
            )
        )
    assert {issue["loc"][0] for issue in error.value.errors()} == {
        "developer_request",
        "reviewer_profile",
    }


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
            max_review_cycles=1,
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
            max_review_cycles=2,
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
            max_review_cycles=1,
            developer_cycles=1,
            reviewer_cycles=1,
            developer_report=completed_developer_report(),
            reviewer_result=final_reviewer_result,
            correlation_id=uuid4(),
        )


def test_result_revalidates_forged_nested_report_and_reviewer_values() -> None:
    """Prevent raw nested values from surviving public terminal-result construction."""
    result = DeveloperReviewerWorkflowResult(
        task_status=TaskStatus.WAITING_QA,
        outcome=WorkflowOutcome.APPROVED,
        max_review_cycles=1,
        developer_cycles=1,
        reviewer_cycles=1,
        developer_report=completed_developer_report(),
        reviewer_result=approved_reviewer_result(),
        correlation_id=uuid4(),
    )
    forged_report = result.developer_report.model_copy(update={"outcome": "SUCCEEDED"})
    forged_reviewer_result = result.reviewer_result.model_copy(
        update={"decision": "APPROVED", "confidence": "0.95"}
    )

    revalidated = DeveloperReviewerWorkflowResult.model_validate(
        result.model_copy(
            update={
                "developer_report": forged_report,
                "reviewer_result": forged_reviewer_result,
            }
        )
    )

    assert revalidated.developer_report.outcome is AgentReportOutcome.SUCCEEDED
    assert revalidated.reviewer_result.decision is ReviewDecision.APPROVED
    assert type(revalidated.reviewer_result.confidence) is float
    assert revalidated.reviewer_result.confidence == 0.95


@pytest.mark.parametrize("max_review_cycles", [0, 11])
def test_result_rejects_review_cycle_limits_outside_workflow_bounds(max_review_cycles: int) -> None:
    """Prevent terminal results from retaining an unbounded configured review limit."""
    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowResult(
            task_status=TaskStatus.WAITING_QA,
            outcome=WorkflowOutcome.APPROVED,
            max_review_cycles=max_review_cycles,
            developer_cycles=1,
            reviewer_cycles=1,
            developer_report=completed_developer_report(),
            reviewer_result=approved_reviewer_result(),
            correlation_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("task_status", "outcome", "max_review_cycles", "cycles", "reviewer_decision"),
    [
        (TaskStatus.WAITING_QA, WorkflowOutcome.APPROVED, 1, 2, ReviewDecision.APPROVED),
        (
            TaskStatus.WAITING_HUMAN,
            WorkflowOutcome.REVIEW_CYCLES_EXHAUSTED,
            2,
            1,
            ReviewDecision.CHANGES_REQUESTED,
        ),
    ],
)
def test_result_requires_cycles_to_truthfully_match_the_configured_limit(
    task_status: TaskStatus,
    outcome: WorkflowOutcome,
    max_review_cycles: int,
    cycles: int,
    reviewer_decision: ReviewDecision,
) -> None:
    """Prevent approval overruns and premature cycle-exhausted terminal results."""
    with pytest.raises(ValidationError):
        DeveloperReviewerWorkflowResult(
            task_status=task_status,
            outcome=outcome,
            max_review_cycles=max_review_cycles,
            developer_cycles=cycles,
            reviewer_cycles=cycles,
            developer_report=completed_developer_report(),
            reviewer_result=approved_reviewer_result().model_copy(
                update={"decision": reviewer_decision}
            ),
            correlation_id=uuid4(),
        )


def test_result_retains_only_final_reports_and_scalar_metadata() -> None:
    """Prevent the workflow result from retaining runtime history or all cycle evidence."""
    result = DeveloperReviewerWorkflowResult(
        task_status=TaskStatus.WAITING_QA,
        outcome=WorkflowOutcome.APPROVED,
        max_review_cycles=1,
        developer_cycles=1,
        reviewer_cycles=1,
        developer_report=completed_developer_report(),
        reviewer_result=approved_reviewer_result(),
        correlation_id=uuid4(),
    )

    assert set(result.model_dump()) == {
        "task_status",
        "outcome",
        "max_review_cycles",
        "developer_cycles",
        "reviewer_cycles",
        "developer_report",
        "reviewer_result",
        "correlation_id",
    }
    assert result.reviewer_result.decision is ReviewDecision.APPROVED


def test_terminal_result_never_retains_handoff_reviewer_profile_or_system_prompt() -> None:
    """Prevent transient handoff profile data from becoming terminal workflow history."""
    profile_marker = "transient reviewer instruction must not enter terminal history"
    context_values = handoff_context_values()
    reviewer_profile = context_values["reviewer_profile"]
    assert isinstance(reviewer_profile, AgentProfile)
    context_values["reviewer_profile"] = reviewer_profile.model_copy(
        update={"system_prompt": profile_marker}
    )
    context = WorkflowHandoffContext.model_validate(context_values)
    result = DeveloperReviewerWorkflowResult(
        task_status=TaskStatus.WAITING_QA,
        outcome=WorkflowOutcome.APPROVED,
        max_review_cycles=1,
        developer_cycles=1,
        reviewer_cycles=1,
        developer_report=completed_developer_report(),
        reviewer_result=approved_reviewer_result(),
        correlation_id=uuid4(),
    )

    assert context.reviewer_profile.system_prompt == profile_marker
    assert "reviewer_profile" not in result.model_dump()
    assert profile_marker not in result.model_dump_json()


def test_error_exposes_only_an_application_owned_safe_message() -> None:
    """Prevent sensitive collaborator or persistence text from crossing the workflow boundary."""
    error = WorkflowError(WorkflowErrorCode.PERSISTENCE_FAILURE)

    assert error.code is WorkflowErrorCode.PERSISTENCE_FAILURE
    assert error.safe_message == "Workflow persistence failed."
    assert str(error) == "Workflow persistence failed."
    with pytest.raises(TypeError):
        WorkflowError(  # type: ignore[call-arg]
            WorkflowErrorCode.PERSISTENCE_FAILURE,
            "caller-controlled text is not an accepted workflow error input",
        )
    with pytest.raises(TypeError):
        WorkflowError("PERSISTENCE_FAILURE")  # type: ignore[arg-type]
