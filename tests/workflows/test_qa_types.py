"""Strict contract tests for the Phase 17 persistent QA workflow stage."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.enums import TaskStatus
from core.qa import QADecision, QAFinding, QAResult, QASeverity
from core.workflows import QAWorkflowOutcome, QAWorkflowRequest, QAWorkflowResult
from tests.qa.factories import qa_request
from tests.workflows.qa_factories import passed_qa_result


def workflow_request(tmp_path: Path) -> QAWorkflowRequest:
    """Build a strict request without persistent database state."""
    request = qa_request(tmp_path)
    return QAWorkflowRequest(
        task_id=request.task_id,
        developer_agent_id=uuid4(),
        reviewer_agent_id=uuid4(),
        qa_agent_id=uuid4(),
        qa_request=request,
        correlation_id=request.correlation_id,
    )


def failed_result(request: QAWorkflowRequest) -> QAResult:
    """Build one actionable functional QA failure."""
    finding = QAFinding(
        category="functional.correctness",
        severity=QASeverity.HIGH,
        reproduction_steps=("Run the focused regression test.",),
        expected_behavior="The calculation returns the sum.",
        actual_behavior="The calculation returns zero.",
    )
    passed = passed_qa_result(request.qa_request)
    return QAResult(
        decision=QADecision.FAILED,
        criteria=passed.criteria,
        findings=(finding,),
        recommendations=(),
        tests=passed.tests,
        rationale="The observed behavior differs from the criterion.",
        confidence=0.9,
        correlation_id=request.correlation_id,
    )


def test_request_revalidates_nested_qa_scope_and_is_immutable(tmp_path: Path) -> None:
    """Detach the nested request instead of trusting validation-bypassing copies."""
    request = workflow_request(tmp_path)
    values = request.model_dump(mode="python")

    canonical = QAWorkflowRequest.model_validate(values)

    assert canonical.qa_request is not request.qa_request
    with pytest.raises(ValidationError):
        canonical.task_id = uuid4()  # type: ignore[misc]


@pytest.mark.parametrize(
    "updates",
    [
        {"reviewer_agent_id": None},
        {"qa_agent_id": None},
    ],
)
def test_request_requires_three_distinct_persistent_agent_ids(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    """Prevent one persistent agent from occupying multiple workflow roles."""
    request = workflow_request(tmp_path)
    values = request.model_dump(mode="python")
    key = next(iter(updates))
    values[key] = values["developer_agent_id"]

    with pytest.raises(ValidationError):
        QAWorkflowRequest.model_validate(values)


@pytest.mark.parametrize("field", ["task_id", "correlation_id"])
def test_request_requires_exact_nested_task_and_correlation(
    tmp_path: Path,
    field: str,
) -> None:
    """Keep top-level workflow scope identical to the nested QA invocation."""
    request = workflow_request(tmp_path)
    values = request.model_dump(mode="python")
    values[field] = uuid4()

    with pytest.raises(ValidationError):
        QAWorkflowRequest.model_validate(values)


@pytest.mark.parametrize(
    ("status", "outcome", "decision"),
    [
        (TaskStatus.WAITING_SECURITY, QAWorkflowOutcome.PASSED, QADecision.PASSED),
        (TaskStatus.CHANGES_REQUESTED, QAWorkflowOutcome.FAILED, QADecision.FAILED),
    ],
)
def test_result_accepts_only_truthful_terminal_pairs(
    tmp_path: Path,
    status: TaskStatus,
    outcome: QAWorkflowOutcome,
    decision: QADecision,
) -> None:
    """Represent only the two functional transitions owned by Phase 17."""
    request = workflow_request(tmp_path)
    qa_result = (
        passed_qa_result(request.qa_request)
        if decision is QADecision.PASSED
        else failed_result(request)
    )

    result = QAWorkflowResult(
        task_status=status,
        outcome=outcome,
        qa_result=qa_result,
        correlation_id=request.correlation_id,
    )

    assert result.qa_result.decision is decision
    assert not hasattr(result, "diff")
    assert not hasattr(result, "acceptance_criteria")


def test_result_rejects_inconsistent_status_outcome_or_correlation(tmp_path: Path) -> None:
    """Prevent a functional QA failure from masquerading as progression."""
    request = workflow_request(tmp_path)
    passed = passed_qa_result(request.qa_request)

    for changes in (
        {"task_status": TaskStatus.CHANGES_REQUESTED},
        {"outcome": QAWorkflowOutcome.FAILED},
        {"correlation_id": uuid4()},
    ):
        values: dict[str, object] = {
            "task_status": TaskStatus.WAITING_SECURITY,
            "outcome": QAWorkflowOutcome.PASSED,
            "qa_result": passed,
            "correlation_id": request.correlation_id,
        }
        values.update(changes)
        with pytest.raises(ValidationError):
            QAWorkflowResult.model_validate(values)
