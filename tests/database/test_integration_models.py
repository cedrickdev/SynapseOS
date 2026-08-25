"""PostgreSQL integration tests for the Phase 2 persistence model."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import (
    AgentRunStatus,
    AgentScoreType,
    AgentSeniority,
    AuditActorType,
    AuditResult,
    ScoreSourceType,
    ToolCallStatus,
)
from infrastructure.database.models import (
    Agent,
    AgentRun,
    AgentScore,
    AuditEvent,
    Decision,
    Project,
    Task,
    TaskDependency,
    ToolCall,
)


def _agent(slug: str = "integration-developer") -> Agent:
    return Agent(
        name="Integration Developer",
        slug=slug,
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )


def test_all_phase_2_entities_round_trip_with_relationships(db_session: Session) -> None:
    agent = _agent()
    project = Project(name="Integration project")
    prerequisite = Task(project=project, title="Foundation")
    task = Task(
        project=project,
        title="Implementation",
        assigned_agent=agent,
        acceptance_criteria=["Tests pass"],
    )
    dependency = TaskDependency(task=task, depends_on_task=prerequisite)
    run = AgentRun(agent=agent, task=task, status=AgentRunStatus.RUNNING)
    decision = Decision(
        decision="Use PostgreSQL",
        alternatives=["SQLite"],
        justification="Production parity",
        evidence=["Migration lifecycle test"],
        confidence=Decimal("0.9000"),
        agent=agent,
        task=task,
    )
    tool_call = ToolCall(
        agent_run=run,
        tool_name="pytest",
        action="run_tests",
        input_data={"scope": "database"},
        output_data={},
        status=ToolCallStatus.RUNNING,
    )
    score = AgentScore(
        agent=agent,
        project=project,
        task=task,
        score_type=AgentScoreType.RELIABILITY,
        value=Decimal("0.8000"),
        justification="Verified result",
        source_type=ScoreSourceType.QA,
        metadata_={"suite": "database"},
    )
    event = AuditEvent(
        actor_type=AuditActorType.AGENT,
        actor_id=agent.slug,
        project=project,
        task=task,
        agent_run=run,
        event_type="TOOL_EXECUTION",
        action="run_tests",
        result=AuditResult.SUCCEEDED,
        data={"tool": "pytest"},
    )
    db_session.add_all([dependency, decision, tool_call, score, event])
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.scalar(select(Task).where(Task.title == "Implementation"))

    assert loaded is not None
    assert loaded.project.name == "Integration project"
    assert loaded.assigned_agent is not None
    assert loaded.assigned_agent.slug == "integration-developer"
    assert loaded.dependencies[0].depends_on_task.title == "Foundation"
    assert loaded.runs[0].tool_calls[0].tool_name == "pytest"
    assert loaded.decisions[0].decision == "Use PostgreSQL"
    assert loaded.scores[0].value == Decimal("0.8000")
    assert loaded.audit_events[0].event_type == "TOOL_EXECUTION"


def test_outer_transaction_fixture_does_not_leak_rows_part_one(db_session: Session) -> None:
    db_session.add(_agent("transaction-isolation-sentinel"))
    db_session.commit()
    assert db_session.scalar(select(Agent).where(Agent.slug == "transaction-isolation-sentinel"))


def test_outer_transaction_fixture_does_not_leak_rows_part_two(db_session: Session) -> None:
    assert (
        db_session.scalar(select(Agent).where(Agent.slug == "transaction-isolation-sentinel"))
        is None
    )
