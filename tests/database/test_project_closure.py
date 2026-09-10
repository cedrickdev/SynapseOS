"""Real-PostgreSQL integration tests for Phase 36 project closure."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.closure.service import ProjectClosureWorkflow
from core.closure.types import ClosurePreconditions, ProjectClosureRequest
from core.enums import (
    AgentSeniority,
    AgentStatus,
    AuditResult,
    ProjectStatus,
    TaskStatus,
)
from core.lessons.types import LessonsLearnedInput
from infrastructure.closure.sqlalchemy import SQLAlchemyProjectClosureStore
from infrastructure.database.models import Agent, AgentScore, AuditEvent, Project, Task


def test_project_closure_archives_project_releases_agents_and_writes_audit(
    db_session: Session,
) -> None:
    agent = Agent(
        name="Closure Developer",
        slug="closure-developer",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
        status=AgentStatus.WORKING,
    )
    project = Project(name="Closure project", status=ProjectStatus.CLIENT_REVIEW)
    completed = Task(
        project=project,
        title="Completed delivery",
        assigned_agent=agent,
        status=TaskStatus.COMPLETED,
    )
    db_session.add_all([project, completed])
    db_session.flush()
    score_count_before = db_session.query(AgentScore).count()

    request = ProjectClosureRequest(
        project_id=project.id,
        preconditions=ClosurePreconditions(
            client_approved=True,
            delivery_complete=True,
            qa_approved=True,
            security_approved=True,
        ),
        retrospective="The delivery was accepted after independent QA and security review.",
        lessons=LessonsLearnedInput(
            project_id=str(project.id),
            project_title=project.name,
            evidence=(),
        ),
    )

    result = ProjectClosureWorkflow(SQLAlchemyProjectClosureStore(db_session)).run(request)
    db_session.commit()

    assert result.delivery_accepted is True
    assert result.metrics.tasks_completed == 1
    assert result.contributions[0].completed_tasks == 1
    assert result.celebrations[0].agent_id == agent.id
    loaded_project = db_session.get(Project, project.id)
    loaded_agent = db_session.get(Agent, agent.id)
    assert loaded_project is not None
    assert loaded_agent is not None
    assert loaded_project.status is ProjectStatus.ARCHIVED
    assert loaded_agent.status is AgentStatus.AVAILABLE
    assert db_session.query(AgentScore).count() == score_count_before
    events = db_session.scalars(select(AuditEvent).where(AuditEvent.project_id == project.id)).all()
    assert {event.event_type for event in events} == {
        "DELIVERY_ACCEPTED",
        "PROJECT_ARCHIVED",
        "AGENT_RELEASED",
    }
    assert all(event.result is AuditResult.SUCCEEDED for event in events)


def test_project_closure_does_not_release_agent_with_other_active_work(
    db_session: Session,
) -> None:
    agent = Agent(
        name="Shared Developer",
        slug="shared-developer",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
        status=AgentStatus.WORKING,
    )
    project = Project(name="Finished project", status=ProjectStatus.CLIENT_REVIEW)
    other_project = Project(name="Other project", status=ProjectStatus.IN_PROGRESS)
    Task(
        project=project,
        title="Finished task",
        assigned_agent=agent,
        status=TaskStatus.COMPLETED,
    )
    Task(
        project=other_project,
        title="Still active",
        assigned_agent=agent,
        status=TaskStatus.IN_PROGRESS,
    )
    db_session.add_all([agent, project, other_project])
    db_session.flush()

    request = ProjectClosureRequest(
        project_id=project.id,
        preconditions=ClosurePreconditions(
            client_approved=True,
            delivery_complete=True,
            qa_approved=True,
            security_approved=True,
        ),
        retrospective="The project was closed without affecting other work.",
        lessons=LessonsLearnedInput(
            project_id=str(project.id),
            project_title=project.name,
            evidence=(),
        ),
    )

    ProjectClosureWorkflow(SQLAlchemyProjectClosureStore(db_session)).run(request)

    loaded_agent = db_session.get(Agent, agent.id)
    assert loaded_agent is not None
    assert loaded_agent.status is AgentStatus.WORKING
