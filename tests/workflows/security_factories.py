"""Hand-checked fixtures for the persistent Phase 18 Security workflow stage."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AgentStatus, ProjectStatus, TaskStatus
from core.security import SecurityRequest, SecurityResult
from core.tools import ToolExecutionContext
from core.workflows import SecurityWorkflowRequest
from core.workspaces import WorkspaceLimits
from infrastructure.database.models import Agent, Project, Task
from infrastructure.workspaces import ManagedWorkspaceFilesystem
from tests.security.factories import security_profile, security_request, source_file


class RecordingSecurityRunner:
    """A runner double whose calls make accidental preflight execution observable."""

    def __init__(self) -> None:
        self.requests: list[SecurityRequest] = []

    async def run(self, request: SecurityRequest) -> SecurityResult:
        self.requests.append(request)
        raise AssertionError("persistent preflight must not invoke Security")


def persisted_security_workflow_request(
    session: Session,
    tmp_path: Path,
    *,
    task_overrides: dict[str, object] | None = None,
    developer_overrides: dict[str, object] | None = None,
    reviewer_overrides: dict[str, object] | None = None,
    qa_overrides: dict[str, object] | None = None,
    security_overrides: dict[str, object] | None = None,
) -> tuple[Task, Agent, Agent, Agent, Agent, SecurityWorkflowRequest]:
    """Persist one coherent WAITING_SECURITY scope and its managed workspace request."""
    project = Project(name="Security workflow project", status=ProjectStatus.IN_PROGRESS)
    agent_values: dict[str, dict[str, object]] = {
        "developer": {
            "name": "Developer One",
            "slug": "developer-01",
            "role": "Developer",
            "department": "engineering",
            "seniority": AgentSeniority.ENGINEER,
            "status": AgentStatus.WORKING,
            "autonomy_level": 2,
            "reputation_score": "0.8000",
            "reliability_score": "0.9000",
        },
        "reviewer": {
            "name": "Reviewer One",
            "slug": "reviewer-01",
            "role": "Reviewer",
            "department": "engineering",
            "seniority": AgentSeniority.SENIOR,
            "status": AgentStatus.WORKING,
            "autonomy_level": 0,
            "reputation_score": "0.8000",
            "reliability_score": "0.9000",
        },
        "qa": {
            "name": "QA One",
            "slug": "qa-01",
            "role": "QA",
            "department": "quality-assurance",
            "seniority": AgentSeniority.SENIOR,
            "status": AgentStatus.WORKING,
            "autonomy_level": 0,
            "reputation_score": "0.8000",
            "reliability_score": "0.9000",
        },
        "security": {
            "name": "Security One",
            "slug": "security-01",
            "role": "Security",
            "department": "security",
            "seniority": AgentSeniority.SENIOR,
            "status": AgentStatus.WORKING,
            "autonomy_level": 0,
            "reputation_score": "0.8000",
            "reliability_score": "0.9000",
        },
    }
    for name, overrides in (
        ("developer", developer_overrides),
        ("reviewer", reviewer_overrides),
        ("qa", qa_overrides),
        ("security", security_overrides),
    ):
        agent_values[name].update(overrides or {})
    developer = Agent(**agent_values["developer"])
    reviewer = Agent(**agent_values["reviewer"])
    qa = Agent(**agent_values["qa"])
    security = Agent(**agent_values["security"])
    session.add_all([project, developer, reviewer, qa, security])
    session.flush()

    task_values: dict[str, object] = {
        "project_id": project.id,
        "title": "Harden the authorization boundary",
        "description": "Validate the reviewed change using bounded security evidence.",
        "status": TaskStatus.WAITING_SECURITY,
        "acceptance_criteria": ["Authorization rejects unauthenticated callers."],
        "assigned_agent_id": developer.id,
    }
    task_values.update(task_overrides or {})
    task = Task(**task_values)
    session.add(task)
    session.flush()

    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / f"managed-{project.id}",
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=8_192,
            max_entries=100,
            max_total_bytes=1_000_000,
            max_depth=8,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
    root = filesystem.promote(project.id, filesystem.create_staging(project.id))
    affected = source_file()
    affected_path = root / affected.path
    affected_path.parent.mkdir(parents=True)
    affected_path.write_text(affected.content, encoding="utf-8")

    correlation_id = uuid4()
    profile = security_profile(
        id=security.slug,
        name=security.name,
        role=security.role,
        department=security.department,
        seniority=security.seniority,
        status=security.status,
        autonomy_level=security.autonomy_level,
    )
    base = security_request(root)
    context = ToolExecutionContext(
        workspace_root=root,
        agent_id=security.slug,
        agent_run_id=uuid4(),
        project_id=project.id,
        task_id=task.id,
        declared_tool_ids=profile.tool_ids,
        correlation_id=correlation_id,
    )
    qa_result = base.qa_result.model_copy(update={"correlation_id": correlation_id})
    nested = SecurityRequest(
        task_id=task.id,
        project_id=project.id,
        developer_id=developer.slug,
        reviewer_id=reviewer.slug,
        qa_id=qa.slug,
        security_id=security.slug,
        profile=profile,
        task_title=task.title,
        task_description=task.description or "",
        acceptance_criteria=tuple(str(item) for item in task.acceptance_criteria),
        diff=base.diff,
        affected_files=(affected,),
        qa_result=qa_result,
        tests=qa_result.tests,
        execution_context=context,
        timeout_seconds=base.timeout_seconds,
        correlation_id=correlation_id,
    )
    request = SecurityWorkflowRequest(
        task_id=task.id,
        developer_agent_id=developer.id,
        reviewer_agent_id=reviewer.id,
        qa_agent_id=qa.id,
        security_agent_id=security.id,
        security_request=nested,
        correlation_id=correlation_id,
    )
    return task, developer, reviewer, qa, security, request
