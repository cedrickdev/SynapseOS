"""Read and insert contracts for append-only repositories."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from core.enums import (
    AgentScoreType,
    AgentSeniority,
    AuditResult,
    ScoreSourceType,
)
from infrastructure.database.models import Agent, AgentScore, AuditEvent, Project, Task
from infrastructure.database.repositories import AgentScoreRepository, AuditEventRepository


def _context(db_session: Session) -> tuple[Agent, Project, Task]:
    agent = Agent(
        name="Repository Agent",
        slug="repository-agent",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    project = Project(name="Repository project")
    task = Task(project=project, title="Repository task", assigned_agent=agent)
    db_session.add(task)
    db_session.flush()
    return agent, project, task


def test_agent_score_repository_add_get_filter_and_paginate(db_session: Session) -> None:
    agent, project, task = _context(db_session)
    repository = AgentScoreRepository(db_session)
    first = repository.add(
        AgentScore(
            agent=agent,
            project=project,
            task=task,
            score_type=AgentScoreType.RELIABILITY,
            value=Decimal("0.7000"),
            justification="First score",
            source_type=ScoreSourceType.QA,
        )
    )
    second = repository.add(
        AgentScore(
            agent=agent,
            project=project,
            score_type=AgentScoreType.SECURITY,
            value=Decimal("0.9000"),
            justification="Second score",
            source_type=ScoreSourceType.SECURITY,
        )
    )
    db_session.commit()

    assert repository.get_by_id(first.id) is first
    assert repository.get_by_id(second.id) is second
    assert repository.list(agent_id=agent.id, score_type=AgentScoreType.SECURITY) == [second]
    assert repository.list(project_id=project.id, task_id=task.id) == [first]
    ordered = repository.list(agent_id=agent.id)
    assert repository.list(agent_id=agent.id, limit=1, offset=1) == ordered[1:2]


def test_audit_repository_add_get_filter_and_paginate(db_session: Session) -> None:
    _, project, task = _context(db_session)
    repository = AuditEventRepository(db_session)
    first = repository.add(
        AuditEvent(
            project=project,
            task=task,
            event_type="TASK_ASSIGNED",
            action="assign_task",
            result=AuditResult.SUCCEEDED,
        )
    )
    second = repository.add(
        AuditEvent(
            project=project,
            event_type="PROJECT_UPDATED",
            action="update_project",
            result=AuditResult.SUCCEEDED,
        )
    )
    db_session.commit()

    assert repository.get_by_id(first.id) is first
    assert repository.list(project_id=project.id, task_id=task.id) == [first]
    assert repository.list(project_id=project.id, event_type="PROJECT_UPDATED") == [second]
    ordered = repository.list(project_id=project.id)
    assert repository.list(project_id=project.id, limit=1, offset=1) == ordered[1:2]


def test_repositories_expose_no_mutation_methods(db_session: Session) -> None:
    forbidden = {"delete", "merge", "save", "update"}

    for repository in (AgentScoreRepository(db_session), AuditEventRepository(db_session)):
        assert forbidden.isdisjoint(dir(repository))
