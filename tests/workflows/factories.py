"""Hand-checked fixtures for Phase 16 workflow contracts."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from core.agents import AgentReport, AgentReportOutcome
from core.commands import CommandProfileId
from core.developer import DeveloperRequest
from core.reviewer import ReviewDecision, ReviewerResult
from tests.developer.factories import request_values
from tests.reviewer.factories import reviewer_profile


def developer_request(tmp_path: Path) -> DeveloperRequest:
    """Build one fully scoped Developer invocation."""
    return DeveloperRequest.model_validate(request_values(tmp_path))


def completed_developer_report() -> AgentReport:
    """Build the final bounded report retained by a workflow result."""
    return AgentReport(
        summary="Implemented the requested correction.",
        outcome=AgentReportOutcome.SUCCEEDED,
        details=("The focused test suite passed.",),
        next_actions=(),
    )


def approved_reviewer_result() -> ReviewerResult:
    """Build one final approval that a workflow may retain."""
    return ReviewerResult(
        decision=ReviewDecision.APPROVED,
        findings=(),
        rationale="The supplied evidence supports approval.",
        confidence=0.95,
        review_score=0.95,
    )


def workflow_request_values(tmp_path: Path) -> dict[str, object]:
    """Build valid workflow request values with persistent UUID identities."""
    request = developer_request(tmp_path)
    return {
        "task_id": uuid4(),
        "developer_agent_id": uuid4(),
        "reviewer_agent_id": uuid4(),
        "developer_request": request,
        "reviewer_profile": reviewer_profile(),
        "max_review_cycles": 2,
        "timeout_seconds": 30.0,
        "correlation_id": request.execution_context.correlation_id,
    }


def canonical_uuid(value: UUID | None = None) -> str:
    """Return hand-checked canonical lower-case UUID text."""
    return str(value or uuid4())


def handoff_context_values() -> dict[str, object]:
    """Build bounded data needed for an independent Reviewer handoff."""
    return {
        "task_id": canonical_uuid(),
        "project_id": canonical_uuid(),
        "task_title": "Correct addition",
        "task_description": "Correct the faulty addition implementation.",
        "acceptance_criteria": ["The existing test suite passes."],
        "developer_id": "developer-01",
        "reviewer_id": "reviewer-01",
        "reviewer_profile": reviewer_profile(),
        "required_check_profiles": [CommandProfileId.PYTEST],
    }
