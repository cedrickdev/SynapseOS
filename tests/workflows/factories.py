"""Hand-checked fixtures for Phase 16 workflow contracts."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from core.agents import AgentReport, AgentReportOutcome
from core.commands import CommandProfileId
from core.developer import DeveloperRequest
from core.enums import AgentSeniority, AgentStatus, ProjectStatus, TaskStatus
from core.reviewer import ReviewDecision, ReviewerResult
from core.runtime import RuntimeTask
from core.tools import ToolExecutionContext
from core.workflows import DeveloperReviewerWorkflowRequest
from infrastructure.database.models import Agent, Project, Task
from tests.developer.factories import developer_profile, request_values
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


def persisted_workflow_request(
    session: Session,
    tmp_path: Path,
    *,
    task_overrides: dict[str, object] | None = None,
    developer_overrides: dict[str, object] | None = None,
    reviewer_overrides: dict[str, object] | None = None,
) -> tuple[Task, Agent, Agent, DeveloperReviewerWorkflowRequest]:
    """Persist one coherent READY workflow scope and return its strict request."""
    project = Project(name="Workflow validation project", status=ProjectStatus.IN_PROGRESS)
    developer_values: dict[str, object] = {
        "name": "Developer One",
        "slug": "developer-01",
        "role": "Developer",
        "department": "engineering",
        "seniority": AgentSeniority.ENGINEER,
        "status": AgentStatus.WORKING,
        "autonomy_level": 2,
        "reputation_score": "0.8000",
        "reliability_score": "0.9000",
    }
    reviewer_values: dict[str, object] = {
        "name": "Reviewer One",
        "slug": "reviewer-01",
        "role": "Reviewer",
        "department": "engineering",
        "seniority": AgentSeniority.SENIOR,
        "status": AgentStatus.WORKING,
        "autonomy_level": 0,
        "reputation_score": "0.8000",
        "reliability_score": "0.9000",
    }
    developer_values.update(developer_overrides or {})
    reviewer_values.update(reviewer_overrides or {})
    developer = Agent(**developer_values)
    reviewer = Agent(**reviewer_values)
    session.add_all([project, developer, reviewer])
    session.flush()

    task_values: dict[str, object] = {
        "project_id": project.id,
        "title": "Correct addition",
        "description": "Correct the faulty addition implementation.",
        "status": TaskStatus.READY,
        "acceptance_criteria": ["The existing test suite passes."],
    }
    task_values.update(task_overrides or {})
    task = Task(**task_values)
    session.add(task)
    session.flush()

    correlation_id = uuid4()
    developer_profile_value = developer_profile()
    runtime_task = RuntimeTask(
        task_id=task.id,
        objective="Correct the faulty addition implementation.",
        acceptance_criteria=("The existing test suite passes.",),
    )
    execution_context = ToolExecutionContext(
        workspace_root=tmp_path,
        agent_id="developer-01",
        agent_run_id=uuid4(),
        project_id=project.id,
        task_id=task.id,
        declared_tool_ids=developer_profile_value.tool_ids,
        correlation_id=correlation_id,
    )
    developer_request_value = DeveloperRequest(
        task=runtime_task,
        profile=developer_profile_value,
        execution_context=execution_context,
        domains=frozenset({"backend"}),
        technologies=frozenset({"python"}),
        tags=frozenset({"testing"}),
        required_check_profiles=(CommandProfileId.PYTEST,),
    )
    request = DeveloperReviewerWorkflowRequest(
        task_id=task.id,
        developer_agent_id=developer.id,
        reviewer_agent_id=reviewer.id,
        developer_request=developer_request_value,
        reviewer_profile=reviewer_profile(),
        max_review_cycles=2,
        timeout_seconds=30.0,
        correlation_id=correlation_id,
    )
    return task, developer, reviewer, request
