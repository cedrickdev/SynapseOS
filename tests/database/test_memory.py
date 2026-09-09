"""Real-PostgreSQL tests for Phase 23 Memory V1."""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from core.enums import AgentSeniority
from core.memory import MemoryScope, MemoryType
from infrastructure.database.models import Agent, Project
from infrastructure.memory import SQLAlchemyMemoryService


def test_create_and_search_agent_project_and_company_memories(db_session: Session) -> None:
    agent = Agent(
        name="Memory Agent",
        slug="memory-agent",
        role="Developer",
        department="Engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    project = Project(name="Memory Project")
    db_session.add_all([agent, project])
    db_session.flush()
    service = SQLAlchemyMemoryService(db_session)

    agent_memory = service.create(
        scope=MemoryScope.AGENT,
        memory_type=MemoryType.FAILURE,
        title="PostgreSQL timeout",
        content="The migration timed out during verification.",
        source="qa-run",
        agent_id=agent.id,
        tags=("postgresql", "migration"),
        confidence=Decimal("0.9"),
    )
    service.create(
        scope=MemoryScope.PROJECT,
        memory_type=MemoryType.DECISION,
        title="Database choice",
        content="Use PostgreSQL for transactional state.",
        source="adr-0001",
        project_id=project.id,
    )
    service.create(
        scope=MemoryScope.COMPANY,
        memory_type=MemoryType.GENERAL,
        title="Review policy",
        content="Authors do not approve their own changes.",
        source="constitution",
    )
    db_session.flush()

    assert service.get(agent_memory.id) == agent_memory
    assert service.search(query="PostgreSQL", scope=MemoryScope.AGENT) == [agent_memory]
    assert service.search(tags=("migration",), agent_id=agent.id) == [agent_memory]


def test_supersession_preserves_old_memory_and_hides_it_from_active_search(
    db_session: Session,
) -> None:
    service = SQLAlchemyMemoryService(db_session)
    old = service.create(
        scope=MemoryScope.COMPANY,
        memory_type=MemoryType.GENERAL,
        title="Test command",
        content="Run pytest without PostgreSQL.",
        source="operator",
    )
    replacement = service.supersede(
        old.id,
        title="Test command",
        content="Run pytest with real PostgreSQL.",
        source="operator-correction",
    )
    db_session.flush()

    assert old.superseded_by_id == replacement.id
    assert service.get(old.id) == old
    assert service.search(query="Test command") == [replacement]
    historical_ids = {entry.id for entry in service.search(query="Test command", active_only=False)}
    assert historical_ids == {old.id, replacement.id}


def test_scope_bindings_are_enforced_before_persistence(db_session: Session) -> None:
    with pytest.raises(ValueError, match="project memory requires project_id"):
        SQLAlchemyMemoryService(db_session).create(
            scope=MemoryScope.PROJECT,
            memory_type=MemoryType.GENERAL,
            title="Invalid",
            content="Missing project scope.",
            source="test",
        )
