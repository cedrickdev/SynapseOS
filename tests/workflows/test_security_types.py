"""Strict contract tests for the Phase 18 persistent Security workflow stage."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.enums import TaskStatus
from core.security import SecurityDecision, SecurityFinding, SecurityResult
from core.workflows import (
    SecurityWorkflowOutcome,
    SecurityWorkflowRequest,
    SecurityWorkflowResult,
)
from tests.security.factories import (
    complete_scanner_summary,
    confirmed_finding,
    security_request,
    suspected_finding,
)


def workflow_request(tmp_path: Path) -> SecurityWorkflowRequest:
    """Build one strict non-persistent workflow request."""
    nested = security_request(tmp_path)
    return SecurityWorkflowRequest(
        task_id=nested.task_id,
        developer_agent_id=uuid4(),
        reviewer_agent_id=uuid4(),
        qa_agent_id=uuid4(),
        security_agent_id=uuid4(),
        security_request=nested,
        correlation_id=nested.correlation_id,
    )


def security_result(decision: SecurityDecision, correlation_id: UUID) -> SecurityResult:
    """Build one truthful result for each Security terminal."""
    findings: tuple[SecurityFinding, ...] = ()
    if decision is SecurityDecision.WARN:
        findings = (suspected_finding(),)
    elif decision is SecurityDecision.BLOCK:
        findings = (confirmed_finding(),)
    return SecurityResult(
        decision=decision,
        findings=findings,
        scanner=complete_scanner_summary(finding_count=len(findings)),
        uncertainty_reasons=(),
        rationale="Bounded evidence supports this Security decision.",
        confidence=0.9,
        correlation_id=correlation_id,
    )


def test_request_reconstructs_nested_security_scope_and_is_immutable(tmp_path: Path) -> None:
    """Detach nested values instead of trusting validation-bypassing copies."""
    request = workflow_request(tmp_path)

    canonical = SecurityWorkflowRequest.model_validate(request.model_dump(mode="python"))

    assert canonical.security_request is not request.security_request
    assert canonical.security_request.profile is not request.security_request.profile
    with pytest.raises(ValidationError):
        canonical.task_id = uuid4()  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    ["reviewer_agent_id", "qa_agent_id", "security_agent_id"],
)
def test_request_requires_four_distinct_persistent_agent_ids(
    tmp_path: Path,
    field: str,
) -> None:
    """Prevent one persistent agent from occupying multiple workflow roles."""
    values = workflow_request(tmp_path).model_dump(mode="python")
    values[field] = values["developer_agent_id"]

    with pytest.raises(ValidationError):
        SecurityWorkflowRequest.model_validate(values)


@pytest.mark.parametrize("field", ["task_id", "correlation_id"])
def test_request_requires_exact_nested_task_and_correlation(
    tmp_path: Path,
    field: str,
) -> None:
    """Keep top-level workflow scope identical to the Security invocation."""
    values = workflow_request(tmp_path).model_dump(mode="python")
    values[field] = uuid4()

    with pytest.raises(ValidationError):
        SecurityWorkflowRequest.model_validate(values)


@pytest.mark.parametrize("field", ["permission_ids", "tool_ids", "skill_ids"])
def test_request_rejects_mutable_forged_security_capabilities_before_serialization(
    tmp_path: Path,
    field: str,
) -> None:
    """Reject mutable forged declarations before model dumping can normalize them."""
    request = workflow_request(tmp_path)
    profile = request.security_request.profile.model_copy(
        update={field: list(getattr(request.security_request.profile, field))}
    )
    nested = request.security_request.model_copy(update={"profile": profile})

    with pytest.raises(ValidationError):
        SecurityWorkflowRequest.model_validate(
            {**request.model_dump(mode="python"), "security_request": nested}
        )


@pytest.mark.parametrize(
    ("status", "outcome", "decision"),
    [
        (TaskStatus.COMPLETED, SecurityWorkflowOutcome.PASS, SecurityDecision.PASS),
        (TaskStatus.WAITING_HUMAN, SecurityWorkflowOutcome.WARN, SecurityDecision.WARN),
        (
            TaskStatus.CHANGES_REQUESTED,
            SecurityWorkflowOutcome.BLOCK,
            SecurityDecision.BLOCK,
        ),
    ],
)
def test_result_accepts_only_truthful_terminal_triples(
    tmp_path: Path,
    status: TaskStatus,
    outcome: SecurityWorkflowOutcome,
    decision: SecurityDecision,
) -> None:
    """Represent only the three terminal transitions owned by Security."""
    request = workflow_request(tmp_path)

    result = SecurityWorkflowResult(
        task_status=status,
        outcome=outcome,
        security_result=security_result(decision, request.correlation_id),
        correlation_id=request.correlation_id,
    )

    assert result.security_result.decision is decision
    assert not hasattr(result, "diff")
    assert not hasattr(result, "affected_files")


def test_result_rejects_inconsistent_terminal_or_correlation(tmp_path: Path) -> None:
    """Prevent a warning or block from masquerading as successful completion."""
    request = workflow_request(tmp_path)
    passed = security_result(SecurityDecision.PASS, request.correlation_id)
    values: dict[str, object] = {
        "task_status": TaskStatus.COMPLETED,
        "outcome": SecurityWorkflowOutcome.PASS,
        "security_result": passed,
        "correlation_id": request.correlation_id,
    }
    for changes in (
        {"task_status": TaskStatus.WAITING_HUMAN},
        {"outcome": SecurityWorkflowOutcome.BLOCK},
        {"correlation_id": uuid4()},
    ):
        with pytest.raises(ValidationError):
            SecurityWorkflowResult.model_validate({**values, **changes})
