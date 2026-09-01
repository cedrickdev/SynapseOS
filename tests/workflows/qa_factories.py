"""Hand-checked fixtures for the persistent Phase 17 QA workflow stage."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from core.commands import CommandCategory, CommandProfileId, CommandTerminalStatus
from core.enums import AgentSeniority, AgentStatus, ProjectStatus, TaskStatus
from core.qa import QADecision, QARequest, QAResult
from core.reviewer import ReviewCheck
from core.tools import ToolExecutionContext
from core.workflows import QAWorkflowRequest
from infrastructure.database.models import Agent, Project, Task
from tests.qa.factories import (
    passed_criterion_assessments,
    qa_profile,
    reviewer_result,
    successful_test_evidence,
)


def passed_qa_result(request: QARequest) -> QAResult:
    """Build one metadata-only passing QA result for workflow tests."""
    return QAResult(
        decision=QADecision.PASSED,
        criteria=passed_criterion_assessments(),
        findings=(),
        recommendations=(),
        tests=(successful_test_evidence(),),
        rationale="Fresh deterministic evidence supports the criterion.",
        confidence=0.90,
        correlation_id=request.correlation_id,
    )


def persisted_qa_workflow_request(
    session: Session,
    tmp_path: Path,
    *,
    task_overrides: dict[str, object] | None = None,
    developer_overrides: dict[str, object] | None = None,
    reviewer_overrides: dict[str, object] | None = None,
    qa_overrides: dict[str, object] | None = None,
) -> tuple[Task, Agent, Agent, Agent, QAWorkflowRequest]:
    """Persist one coherent WAITING_QA scope and return its strict request."""
    project = Project(name="QA workflow project", status=ProjectStatus.IN_PROGRESS)
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
    qa_values: dict[str, object] = {
        "name": "QA One",
        "slug": "qa-01",
        "role": "QA",
        "department": "quality-assurance",
        "seniority": AgentSeniority.SENIOR,
        "status": AgentStatus.WORKING,
        "autonomy_level": 0,
        "reputation_score": "0.8000",
        "reliability_score": "0.9000",
    }
    developer_values.update(developer_overrides or {})
    reviewer_values.update(reviewer_overrides or {})
    qa_values.update(qa_overrides or {})
    developer = Agent(**developer_values)
    reviewer = Agent(**reviewer_values)
    qa = Agent(**qa_values)
    session.add_all([project, developer, reviewer, qa])
    session.flush()

    task_values: dict[str, object] = {
        "project_id": project.id,
        "title": "Correct addition",
        "description": "Correct the faulty addition implementation.",
        "status": TaskStatus.WAITING_QA,
        "acceptance_criteria": ["The existing test suite passes."],
        "assigned_agent_id": developer.id,
    }
    task_values.update(task_overrides or {})
    task = Task(**task_values)
    session.add(task)
    session.flush()

    correlation_id = uuid4()
    profile = qa_profile()
    context = ToolExecutionContext(
        workspace_root=tmp_path,
        agent_id=qa.slug,
        agent_run_id=uuid4(),
        project_id=project.id,
        task_id=task.id,
        declared_tool_ids=profile.tool_ids,
        correlation_id=correlation_id,
    )
    qa_request = QARequest(
        task_id=task.id,
        project_id=project.id,
        developer_id=developer.slug,
        reviewer_id=reviewer.slug,
        qa_id=qa.slug,
        profile=profile,
        task_title=task.title,
        task_description=task.description or "",
        acceptance_criteria=tuple(str(item) for item in task.acceptance_criteria),
        diff="--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n-return 0\n+return a + b\n",
        reviewer_result=reviewer_result(),
        existing_checks=(
            ReviewCheck(
                profile_id=CommandProfileId.PYTEST,
                category=CommandCategory.TEST,
                status=CommandTerminalStatus.SUCCEEDED,
                exit_code=0,
                truncated=False,
            ),
        ),
        required_test_profiles=(CommandProfileId.PYTEST,),
        execution_context=context,
        timeout_seconds=30.0,
        correlation_id=correlation_id,
    )
    request = QAWorkflowRequest(
        task_id=task.id,
        developer_agent_id=developer.id,
        reviewer_agent_id=reviewer.id,
        qa_agent_id=qa.id,
        qa_request=qa_request,
        correlation_id=correlation_id,
    )
    return task, developer, reviewer, qa, request
