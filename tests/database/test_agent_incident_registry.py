"""Real-PostgreSQL tests for the Agent Incident Registry."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from core.autonomy import AutonomyLevel
from core.enums import AgentRunStatus, AgentSeniority, AgentStatus
from core.incidents import IncidentSeverity
from core.manager import AgentIncidentStatus
from infrastructure.database.models import Agent, AgentIncident, AgentRun, Project, Task
from infrastructure.database.repositories.agent_incidents import (
    AgentIncidentRepository,
    AgentIncidentScopeError,
)


def _scope(session: Session) -> tuple[Project, Agent, Task, AgentRun]:
    agent = Agent(
        name="Incident Agent",
        slug=f"incident-agent-{uuid4().hex}",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.WORKING,
    )
    project = Project(name="Agent incident project")
    task = Task(project=project, title="Investigate governed failure", assigned_agent=agent)
    run = AgentRun(agent=agent, task=task, status=AgentRunStatus.RUNNING, iteration=1)
    session.add_all([agent, project, task, run])
    session.flush()
    return project, agent, task, run


def _incident(project: Project, agent: Agent, task: Task, run: AgentRun) -> AgentIncident:
    now = datetime.now(UTC)
    return AgentIncident(
        project_id=project.id,
        task_id=task.id,
        run_id=run.id,
        agent_id=agent.id,
        severity=IncidentSeverity.HIGH,
        status=AgentIncidentStatus.CONTAINED,
        trigger="Repeated out-of-scope tool request.",
        first_detected_at=now,
        contained_at=now,
        trust_before=Decimal("93.00"),
        trust_after=Decimal("61.00"),
        autonomy_before=AutonomyLevel.BOUNDED_AUTONOMY,
        autonomy_after=AutonomyLevel.RECOMMEND,
        affected_resources=["workspace://project/source"],
        execution_graph_ref="execution-graph://run/1",
        delegation_chain_ref="delegation://chain/1",
        communication_graph_ref=None,
        policy_violations=["OUT_OF_SCOPE_ACTION"],
        security_findings=["security-finding://1"],
        corrective_actions=[],
    )


def test_repository_persists_and_reads_scoped_agent_incidents(db_session: Session) -> None:
    project, agent, task, run = _scope(db_session)
    repository = AgentIncidentRepository(db_session)
    incident = repository.add(_incident(project, agent, task, run))
    db_session.flush()

    assert repository.get(incident.id) is incident
    assert repository.list(project_id=project.id, agent_id=agent.id, limit=10) == [incident]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_repository_rejects_cross_scope_agent_incident(db_session: Session) -> None:
    project, agent, task, run = _scope(db_session)
    other_project = Project(name="Unrelated project")
    db_session.add(other_project)
    db_session.flush()
    incident = _incident(project, agent, task, run)
    incident.project_id = other_project.id

    with pytest.raises(AgentIncidentScopeError, match="scope"):
        AgentIncidentRepository(db_session).add(incident)
