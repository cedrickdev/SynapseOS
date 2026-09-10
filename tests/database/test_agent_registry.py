"""Real-PostgreSQL Phase 28 agent registry tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.agent_registry import AgentCostEstimate, AgentMatcher, AgentMatchingRequest, AgentRegistry
from core.domain_decomposition import DomainWorkstream, WorkstreamScope
from core.enums import (
    AgentSeniority,
    AgentStatus,
    AuditActorType,
    Permission,
    ToolRiskLevel,
)
from infrastructure.agent_registry import SQLAlchemyAgentRegistrySource
from infrastructure.database.models import Agent, AgentCapability, AgentPermission, Project


def _agent(*, slug: str, status: AgentStatus = AgentStatus.AVAILABLE) -> Agent:
    return Agent(
        name=slug.replace("-", " ").title(),
        slug=slug,
        role="Backend Engineer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=status,
        autonomy_level=2,
        reputation_score=Decimal("0.8100"),
        reliability_score=Decimal("0.9200"),
    )


def _grant(
    *,
    agent: Agent,
    permission: Permission,
    now: datetime,
    project: Project | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> AgentPermission:
    return AgentPermission(
        agent=agent,
        project=project,
        permission=permission,
        granted_by_actor_type=AuditActorType.HUMAN,
        granted_by_actor_id="platform-admin",
        reason="Phase 28 registry fixture",
        expires_at=expires_at if expires_at is not None else now + timedelta(days=1),
        revoked_at=revoked_at,
    )


def test_registry_reads_bounded_company_agents_with_active_project_authority(
    db_session: Session,
) -> None:
    now = datetime(2030, 9, 10, 12, 0, tzinfo=UTC)
    project = Project(name="Registry project")
    other_project = Project(name="Other project")
    available = _agent(slug="available-agent")
    busy = _agent(slug="busy-agent", status=AgentStatus.WORKING)
    db_session.add_all([project, other_project, available, busy])
    db_session.flush()
    db_session.add_all(
        [
            AgentCapability(
                agent=available,
                capability="backend-engineering",
                expertise_score=Decimal("0.9000"),
            ),
            AgentCapability(
                agent=available,
                capability="payment-security",
                expertise_score=Decimal("0.8500"),
            ),
            AgentCapability(
                agent=available,
                capability="inactive-capability",
                expertise_score=Decimal("1.0000"),
                active=False,
            ),
            AgentCapability(
                agent=busy,
                capability="backend-engineering",
                expertise_score=Decimal("0.7000"),
            ),
            _grant(agent=available, permission=Permission.FILESYSTEM_READ, now=now),
            _grant(
                agent=available,
                project=project,
                permission=Permission.FILESYSTEM_READ,
                now=now,
            ),
            _grant(
                agent=available,
                project=project,
                permission=Permission.GIT_READ,
                now=now,
            ),
            _grant(
                agent=available,
                project=other_project,
                permission=Permission.NETWORK_ACCESS,
                now=now,
            ),
            _grant(
                agent=available,
                permission=Permission.DATABASE_READ,
                now=now,
                expires_at=now - timedelta(seconds=1),
            ),
            _grant(
                agent=available,
                permission=Permission.TESTS_EXECUTE,
                now=now,
                revoked_at=now,
            ),
        ]
    )
    db_session.flush()
    source = SQLAlchemyAgentRegistrySource(db_session, clock=lambda: now)
    registry = AgentRegistry(source)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit is forbidden")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback is forbidden")),
        patch.object(db_session, "close", side_effect=AssertionError("close is forbidden")),
    ):
        candidates = registry.list_candidates(project_id=project.id, limit=10)

    assert {candidate.slug for candidate in candidates} == {"available-agent", "busy-agent"}
    available_candidate = {candidate.slug: candidate for candidate in candidates}["available-agent"]
    assert [item.name for item in available_candidate.capabilities] == [
        "backend-engineering",
        "payment-security",
    ]
    assert [item.expertise for item in available_candidate.capabilities] == [
        Decimal("0.9000"),
        Decimal("0.8500"),
    ]
    assert available_candidate.active_permissions == (
        Permission.FILESYSTEM_READ,
        Permission.GIT_READ,
    )
    assert available_candidate.reputation == Decimal("0.8100")
    assert available_candidate.reliability == Decimal("0.9200")


def test_agent_capabilities_are_company_scoped_and_database_constrained(
    db_session: Session,
) -> None:
    agent = _agent(slug=f"capability-agent-{uuid.uuid4().hex}")
    db_session.add(agent)
    db_session.flush()
    db_session.add(
        AgentCapability(
            agent=agent,
            capability="backend-engineering",
            expertise_score=Decimal("0.5000"),
        )
    )
    db_session.flush()

    db_session.add(
        AgentCapability(
            agent=agent,
            capability="backend-engineering",
            expertise_score=Decimal("0.6000"),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("capability", "expertise"),
    [
        ("Backend Engineering", Decimal("0.5000")),
        ("backend-engineering", Decimal("1.0001")),
        ("backend-engineering", Decimal("-0.0001")),
    ],
)
def test_agent_capability_identifiers_and_expertise_are_database_constrained(
    db_session: Session,
    capability: str,
    expertise: Decimal,
) -> None:
    agent = _agent(slug=f"invalid-capability-agent-{uuid.uuid4().hex}")
    db_session.add(agent)
    db_session.flush()
    db_session.add(
        AgentCapability(
            agent=agent,
            capability=capability,
            expertise_score=expertise,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_postgresql_registry_snapshots_feed_matcher_without_assignment(
    db_session: Session,
) -> None:
    now = datetime(2030, 9, 10, 12, 0, tzinfo=UTC)
    project = Project(name="Matching project")
    available = _agent(slug="matching-agent")
    busy = _agent(slug="occupied-agent", status=AgentStatus.WORKING)
    db_session.add_all([project, available, busy])
    db_session.flush()
    for agent in (available, busy):
        db_session.add_all(
            [
                AgentCapability(
                    agent=agent,
                    capability="backend-engineering",
                    expertise_score=Decimal("0.9000"),
                ),
                AgentCapability(
                    agent=agent,
                    capability="payment-security",
                    expertise_score=Decimal("0.9000"),
                ),
                _grant(
                    agent=agent,
                    permission=Permission.FILESYSTEM_READ,
                    now=now,
                ),
            ]
        )
    db_session.flush()
    candidates = AgentRegistry(
        SQLAlchemyAgentRegistrySource(db_session, clock=lambda: now)
    ).list_candidates(project_id=project.id)
    workstream = DomainWorkstream(
        id="payments",
        name="Payments",
        scope_kind=WorkstreamScope.DOMAIN,
        purpose="Own payment processing.",
        source_domains=("Payments",),
        responsibilities=("Process payments",),
        required_capabilities=("backend-engineering", "payment-security"),
        dependencies=(),
    )
    request = AgentMatchingRequest(
        project_id=project.id,
        workstream=workstream,
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=tuple(
            AgentCostEstimate(agent_id=candidate.agent_id, normalized_cost=Decimal("0.2000"))
            for candidate in candidates
        ),
    )

    result = AgentMatcher().match(request, candidates)

    assert [match.agent.agent_id for match in result.matches] == [available.id]
    assert result.rejections[0].agent_id == busy.id
    assert result.rejections[0].reasons == ("Agent is not available.",)
    assert available.status is AgentStatus.AVAILABLE
    assert busy.status is AgentStatus.WORKING


def test_registry_reads_never_autoflush_pending_session_changes(db_session: Session) -> None:
    now = datetime(2030, 9, 10, 12, 0, tzinfo=UTC)
    project = Project(name="No autoflush project")
    agent = _agent(slug="no-autoflush-agent")
    persisted = AgentCapability(
        agent=agent,
        capability="backend-engineering",
        expertise_score=Decimal("0.8000"),
    )
    db_session.add_all([project, agent, persisted])
    db_session.flush()
    pending_duplicate = AgentCapability(
        agent=agent,
        capability="backend-engineering",
        expertise_score=Decimal("0.9000"),
    )
    db_session.add(pending_duplicate)

    candidates = AgentRegistry(
        SQLAlchemyAgentRegistrySource(db_session, clock=lambda: now)
    ).list_candidates(project_id=project.id)

    assert [candidate.agent_id for candidate in candidates] == [agent.id]
    assert candidates[0].capabilities[0].expertise == Decimal("0.8000")
    assert pending_duplicate in db_session.new
