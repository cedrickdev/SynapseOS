"""Database-enforced constraint tests against PostgreSQL."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AgentScoreType, AgentSeniority, ScoreSourceType
from infrastructure.database.models import (
    Agent,
    AgentRun,
    AgentScore,
    Decision,
    Project,
    Task,
    TaskDependency,
)


def _agent(slug: str, **values: object) -> Agent:
    return Agent(
        name="Constraint Agent",
        slug=slug,
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
        **values,
    )


def _work(db_session: Session) -> tuple[Agent, Project, Task]:
    agent = _agent("constraint-agent")
    project = Project(name="Constraint project")
    task = Task(project=project, title="Constraint task", assigned_agent=agent)
    db_session.add(task)
    db_session.flush()
    return agent, project, task


@pytest.mark.parametrize(
    ("values", "slug"),
    [
        ({"autonomy_level": 6}, "bad-autonomy"),
        ({"reputation_score": Decimal("1.0001")}, "bad-reputation"),
        ({"reliability_score": Decimal("-0.0001")}, "bad-reliability"),
    ],
)
def test_agent_bounds_are_enforced(
    db_session: Session, values: dict[str, object], slug: str
) -> None:
    db_session.add(_agent(slug, **values))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_agent_slug_is_unique(db_session: Session) -> None:
    db_session.add_all([_agent("duplicate"), _agent("duplicate")])
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "task",
    [
        Task(title="Zero iterations", max_iterations=0),
        Task(title="Too many iterations", max_iterations=2, iteration_count=3),
    ],
)
def test_task_iteration_bounds_are_enforced(db_session: Session, task: Task) -> None:
    project = Project(name=f"Project for {task.title}")
    task.project = project
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_dependencies_reject_duplicates_and_self_edges(db_session: Session) -> None:
    _, project, task = _work(db_session)
    prerequisite = Task(project=project, title="Prerequisite")
    db_session.add(prerequisite)
    db_session.flush()
    db_session.add_all(
        [
            TaskDependency(task=task, depends_on_task=prerequisite),
            TaskDependency(task=task, depends_on_task=prerequisite),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_dependency_rejects_self_edge(db_session: Session) -> None:
    _, _, task = _work(db_session)
    db_session.add(TaskDependency(task=task, depends_on_task=task))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("confidence", [Decimal("-0.0001"), Decimal("1.0001")])
def test_confidence_bounds_are_enforced(db_session: Session, confidence: Decimal) -> None:
    agent, _, task = _work(db_session)
    db_session.add_all(
        [
            AgentRun(agent=agent, task=task, confidence=confidence),
            Decision(
                decision="Invalid confidence",
                justification="Constraint test",
                confidence=confidence,
                agent=agent,
                task=task,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_score_bounds_are_enforced(db_session: Session) -> None:
    agent, _, _ = _work(db_session)
    db_session.add(
        AgentScore(
            agent=agent,
            score_type=AgentScoreType.RELIABILITY,
            value=Decimal("1.0001"),
            justification="Invalid score",
            source_type=ScoreSourceType.SYSTEM,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_historical_foreign_keys_restrict_parent_deletion(db_session: Session) -> None:
    agent, _, _ = _work(db_session)
    db_session.add(
        AgentScore(
            agent=agent,
            score_type=AgentScoreType.RELIABILITY,
            value=Decimal("0.5000"),
            justification="Historical score",
            source_type=ScoreSourceType.SYSTEM,
        )
    )
    db_session.commit()
    db_session.delete(agent)
    with pytest.raises(IntegrityError):
        db_session.flush()
