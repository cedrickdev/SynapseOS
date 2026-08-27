"""Real-model setup helpers for Phase 6 tool audit tests."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import (
    AgentRunStatus,
    AgentSeniority,
    AgentStatus,
    ProjectStatus,
    TaskStatus,
)
from infrastructure.database.models import Agent, AgentRun, Project, Task


def create_tool_run(session: Session) -> tuple[Project, Agent, Task, AgentRun]:
    """Persist one coherent project/agent/task/run scope for a tool invocation."""
    project = Project(
        name="Tool Audit Project",
        status=ProjectStatus.IN_PROGRESS,
    )
    agent = session.scalar(select(Agent).where(Agent.slug == "backend-agent-03"))
    if agent is None:
        agent = Agent(
            name="Backend Agent 03",
            slug="backend-agent-03",
            role="Backend Engineer",
            department="engineering",
            seniority=AgentSeniority.SENIOR,
            status=AgentStatus.WORKING,
            autonomy_level=2,
            reputation_score=Decimal("0.9000"),
            reliability_score=Decimal("0.9200"),
        )
    session.add_all([project, agent])
    session.flush()
    task = Task(
        project_id=project.id,
        assigned_agent_id=agent.id,
        title="Exercise a read-only tool",
        status=TaskStatus.IN_PROGRESS,
    )
    session.add(task)
    session.flush()
    run = AgentRun(
        agent_id=agent.id,
        task_id=task.id,
        status=AgentRunStatus.RUNNING,
        iteration=1,
    )
    session.add(run)
    session.flush()
    return project, agent, task, run
