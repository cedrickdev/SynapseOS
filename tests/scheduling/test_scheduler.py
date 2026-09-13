"""Tests for deterministic Phase 43 multi-project scheduling."""

from __future__ import annotations

import uuid
from decimal import Decimal

from core.agent_registry import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentCostEstimate,
    AgentMatchingRequest,
)
from core.domain_decomposition import DomainWorkstream, WorkstreamScope
from core.enums import AgentSeniority, AgentStatus, Permission, ToolRiskLevel
from core.scheduling import ProjectScheduler, ProjectScheduleRequest


def _workstream() -> DomainWorkstream:
    return DomainWorkstream(
        id="payments",
        name="Payments",
        scope_kind=WorkstreamScope.DOMAIN,
        purpose="Own payment processing and reconciliation.",
        source_domains=("Payments",),
        responsibilities=("Process payments",),
        required_capabilities=("backend-engineering",),
        dependencies=(),
    )


def _candidate(
    agent_id: uuid.UUID,
    slug: str,
    *,
    status: AgentStatus = AgentStatus.AVAILABLE,
) -> AgentCandidate:
    return AgentCandidate(
        agent_id=agent_id,
        slug=slug,
        seniority=AgentSeniority.SENIOR,
        status=status,
        autonomy_level=2,
        reputation=Decimal("0.8000"),
        reliability=Decimal("0.8000"),
        capabilities=(
            AgentCapabilitySnapshot(name="backend-engineering", expertise=Decimal("0.9000")),
        ),
        active_permissions=(Permission.FILESYSTEM_READ,),
    )


def _request(project_id: uuid.UUID, task_id: uuid.UUID, priority: int) -> ProjectScheduleRequest:
    return ProjectScheduleRequest(
        project_id=project_id,
        task_id=task_id,
        project_priority=priority,
        matching_request=AgentMatchingRequest(
            project_id=project_id,
            workstream=_workstream(),
            required_permissions=(Permission.FILESYSTEM_READ,),
            minimum_seniority=AgentSeniority.ENGINEER,
            risk_level=ToolRiskLevel.HIGH,
            cost_estimates=(),
        ),
    )


def _with_cost(
    request: ProjectScheduleRequest,
    agent_ids: tuple[uuid.UUID, ...],
) -> ProjectScheduleRequest:
    return request.model_copy(
        update={
            "matching_request": request.matching_request.model_copy(
                update={
                    "cost_estimates": tuple(
                        AgentCostEstimate(agent_id=agent_id, normalized_cost=Decimal("0.1000"))
                        for agent_id in agent_ids
                    )
                }
            )
        }
    )


def test_scheduler_prioritizes_projects_and_assigns_each_available_agent_once() -> None:
    async_agent = uuid.UUID("00000000-0000-0000-0000-000000000001")
    backup_agent = uuid.UUID("00000000-0000-0000-0000-000000000002")
    first_project, second_project = uuid.uuid4(), uuid.uuid4()
    scheduler = ProjectScheduler()
    requests = (
        _with_cost(_request(second_project, uuid.uuid4(), 10), (async_agent, backup_agent)),
        _with_cost(_request(first_project, uuid.uuid4(), 90), (async_agent, backup_agent)),
    )

    assignments = scheduler.schedule(
        requests,
        (_candidate(async_agent, "primary"), _candidate(backup_agent, "backup")),
    )

    assert [assignment.project_id for assignment in assignments] == [first_project, second_project]
    assert len({assignment.agent_id for assignment in assignments}) == 2


def test_scheduler_does_not_assign_an_agent_already_active_on_another_project() -> None:
    agent_id = uuid.uuid4()
    scheduler = ProjectScheduler()
    first = _with_cost(_request(uuid.uuid4(), uuid.uuid4(), 50), (agent_id,))
    second = _with_cost(_request(uuid.uuid4(), uuid.uuid4(), 50), (agent_id,))
    candidate = _candidate(agent_id, "shared-agent")

    assert len(scheduler.schedule((first,), (candidate,))) == 1
    assert scheduler.schedule((second,), (candidate,)) == ()


def test_scheduler_release_returns_agents_to_the_pool_and_preserves_history() -> None:
    agent_id = uuid.uuid4()
    project_id = uuid.uuid4()
    scheduler = ProjectScheduler()
    request = _with_cost(_request(project_id, uuid.uuid4(), 50), (agent_id,))
    candidate = _candidate(agent_id, "releasable-agent")

    scheduler.schedule((request,), (candidate,))
    assert scheduler.release_project(project_id) == 1
    reassigned = scheduler.schedule(
        (_with_cost(_request(uuid.uuid4(), uuid.uuid4(), 50), (agent_id,)),),
        (candidate,),
    )

    assert len(reassigned) == 1
    assert len(scheduler.history()) == 2
    assert scheduler.history()[0].released_at is not None
