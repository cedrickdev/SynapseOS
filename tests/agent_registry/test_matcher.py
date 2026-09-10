"""Deterministic Phase 28 agent matching tests."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.agent_registry import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentCostEstimate,
    AgentMatcher,
    AgentMatchingRequest,
)
from core.domain_decomposition import DomainWorkstream, WorkstreamScope
from core.enums import AgentSeniority, AgentStatus, Permission, ToolRiskLevel


def _workstream() -> DomainWorkstream:
    return DomainWorkstream(
        id="payments",
        name="Payments",
        scope_kind=WorkstreamScope.DOMAIN,
        purpose="Own payment processing and reconciliation.",
        source_domains=("Payments",),
        responsibilities=("Process payments", "Reconcile transactions"),
        required_capabilities=("backend-engineering", "payment-security"),
        dependencies=(),
    )


def _candidate(
    *,
    agent_id: uuid.UUID,
    slug: str,
    expertise: Decimal,
    status: AgentStatus = AgentStatus.AVAILABLE,
    autonomy_level: int = 2,
    permissions: tuple[Permission, ...] = (Permission.FILESYSTEM_READ,),
    capabilities: tuple[str, ...] = ("backend-engineering", "payment-security"),
    reputation: Decimal = Decimal("0.8000"),
    reliability: Decimal = Decimal("0.8000"),
    seniority: AgentSeniority = AgentSeniority.SENIOR,
) -> AgentCandidate:
    return AgentCandidate(
        agent_id=agent_id,
        slug=slug,
        seniority=seniority,
        status=status,
        autonomy_level=autonomy_level,
        reputation=reputation,
        reliability=reliability,
        capabilities=tuple(
            AgentCapabilitySnapshot(name=name, expertise=expertise) for name in capabilities
        ),
        active_permissions=permissions,
    )


def _request(*costs: AgentCostEstimate, limit: int = 10) -> AgentMatchingRequest:
    return AgentMatchingRequest(
        project_id=uuid.uuid4(),
        workstream=_workstream(),
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=costs,
        limit=limit,
    )


def test_matcher_ranks_eligible_agents_deterministically_with_explanations() -> None:
    strong_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    frugal_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    strong = _candidate(
        agent_id=strong_id,
        slug="strong-agent",
        expertise=Decimal("0.9500"),
        reputation=Decimal("0.9000"),
        reliability=Decimal("0.9000"),
    )
    frugal = _candidate(
        agent_id=frugal_id,
        slug="frugal-agent",
        expertise=Decimal("0.7000"),
    )
    request = _request(
        AgentCostEstimate(agent_id=strong_id, normalized_cost=Decimal("0.7000")),
        AgentCostEstimate(agent_id=frugal_id, normalized_cost=Decimal("0.1000")),
    )

    first = AgentMatcher().match(request, (frugal, strong))
    second = AgentMatcher().match(request, (strong, frugal))

    assert [match.agent.agent_id for match in first.matches] == [strong_id, frugal_id]
    assert first == second
    assert first.matches[0].score == Decimal("0.7975")
    assert first.matches[0].breakdown.expertise == Decimal("0.9500")
    assert first.matches[0].breakdown.cost_efficiency == Decimal("0.3000")
    assert first.matches[0].explanation == (
        "All required capabilities are active.",
        "All required permissions are active for the project scope.",
        "Autonomy level satisfies HIGH risk.",
    )
    assert first.rejections == ()


@pytest.mark.parametrize(
    ("candidate", "cost", "reason"),
    [
        (
            _candidate(
                agent_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
                slug="busy",
                expertise=Decimal("0.9000"),
                status=AgentStatus.WORKING,
            ),
            Decimal("0.2000"),
            "Agent is not available.",
        ),
        (
            _candidate(
                agent_id=uuid.UUID("00000000-0000-0000-0000-000000000012"),
                slug="incapable",
                expertise=Decimal("0.9000"),
                capabilities=("backend-engineering",),
            ),
            Decimal("0.2000"),
            "Missing required capabilities: payment-security.",
        ),
        (
            _candidate(
                agent_id=uuid.UUID("00000000-0000-0000-0000-000000000013"),
                slug="untrusted",
                expertise=Decimal("0.9000"),
                permissions=(),
            ),
            Decimal("0.2000"),
            "Missing required permissions: filesystem.read.",
        ),
        (
            _candidate(
                agent_id=uuid.UUID("00000000-0000-0000-0000-000000000014"),
                slug="under-authorized",
                expertise=Decimal("0.9000"),
                autonomy_level=1,
            ),
            Decimal("0.2000"),
            "Autonomy level is below the HIGH risk requirement.",
        ),
    ],
)
def test_matcher_rejects_ineligible_candidates(
    candidate: AgentCandidate,
    cost: Decimal,
    reason: str,
) -> None:
    request = _request(AgentCostEstimate(agent_id=candidate.agent_id, normalized_cost=cost))

    result = AgentMatcher().match(request, (candidate,))

    assert result.matches == ()
    assert result.rejections[0].agent_id == candidate.agent_id
    assert reason in result.rejections[0].reasons


def test_matcher_requires_explicit_cost_and_returns_only_the_requested_limit() -> None:
    first_id = uuid.UUID("00000000-0000-0000-0000-000000000021")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000022")
    first = _candidate(agent_id=first_id, slug="first", expertise=Decimal("0.8000"))
    second = _candidate(agent_id=second_id, slug="second", expertise=Decimal("0.7000"))
    request = _request(
        AgentCostEstimate(agent_id=first_id, normalized_cost=Decimal("0.2000")),
        limit=1,
    )

    result = AgentMatcher().match(request, (second, first))

    assert len(result.matches) == 1
    assert result.matches[0].agent.agent_id == first_id
    assert result.rejections[0].reasons == ("No task cost estimate was supplied.",)


def test_seniority_changes_ranking_between_otherwise_equal_eligible_agents() -> None:
    engineer_id = uuid.UUID("00000000-0000-0000-0000-000000000031")
    principal_id = uuid.UUID("00000000-0000-0000-0000-000000000032")
    engineer = _candidate(
        agent_id=engineer_id,
        slug="engineer-agent",
        expertise=Decimal("0.8000"),
        seniority=AgentSeniority.ENGINEER,
    )
    principal = _candidate(
        agent_id=principal_id,
        slug="principal-agent",
        expertise=Decimal("0.8000"),
        seniority=AgentSeniority.PRINCIPAL,
    )
    request = _request(
        AgentCostEstimate(agent_id=engineer_id, normalized_cost=Decimal("0.2000")),
        AgentCostEstimate(agent_id=principal_id, normalized_cost=Decimal("0.2000")),
    )

    result = AgentMatcher().match(request, (engineer, principal))

    assert [match.agent.agent_id for match in result.matches] == [principal_id, engineer_id]
    assert result.matches[0].breakdown.seniority_fit == Decimal("1.0000")
    assert result.matches[1].breakdown.seniority_fit == Decimal("0.4000")


def test_matching_contracts_are_bounded_and_immutable() -> None:
    agent_id = uuid.uuid4()
    candidate = _candidate(agent_id=agent_id, slug="bounded", expertise=Decimal("0.8000"))
    with pytest.raises(ValidationError):
        candidate.slug = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _request(
            AgentCostEstimate(agent_id=agent_id, normalized_cost=Decimal("0.1000")),
            limit=101,
        )
