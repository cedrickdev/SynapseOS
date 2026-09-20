"""Tests for the read-only Agent Genome signal used by manager selection."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.agent_registry import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentCostEstimate,
    AgentGenomeCapabilitySignal,
    AgentGenomeManagerSignal,
    AgentGenomeManagerSignalMatcher,
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
        responsibilities=("Process payments",),
        required_capabilities=("backend-engineering", "payment-security"),
        dependencies=(),
    )


def _candidate(agent_id: uuid.UUID, slug: str, expertise: Decimal) -> AgentCandidate:
    return AgentCandidate(
        agent_id=agent_id,
        slug=slug,
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
        autonomy_level=3,
        reputation=Decimal("0.8000"),
        reliability=Decimal("0.8000"),
        capabilities=(
            AgentCapabilitySnapshot(name="backend-engineering", expertise=expertise),
            AgentCapabilitySnapshot(name="payment-security", expertise=expertise),
        ),
        active_permissions=(Permission.FILESYSTEM_READ,),
    )


def test_genome_signal_conservatively_adjusts_manager_selection() -> None:
    observed_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    fallback_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    request = AgentMatchingRequest(
        project_id=uuid.uuid4(),
        workstream=_workstream(),
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=(
            AgentCostEstimate(agent_id=observed_agent_id, normalized_cost=Decimal("0.2000")),
            AgentCostEstimate(agent_id=fallback_agent_id, normalized_cost=Decimal("0.2000")),
        ),
    )
    signal = AgentGenomeManagerSignal(
        agent_id=observed_agent_id,
        genome_version_id=uuid.uuid4(),
        capabilities=(
            AgentGenomeCapabilitySignal(
                capability_key="backend-engineering",
                score=Decimal("0.2000"),
                confidence=Decimal("1.0000"),
            ),
            AgentGenomeCapabilitySignal(
                capability_key="payment-security",
                score=Decimal("0.2000"),
                confidence=Decimal("1.0000"),
            ),
        ),
    )

    result = AgentGenomeManagerSignalMatcher().match(
        request,
        candidates=(
            _candidate(observed_agent_id, "observed-agent", Decimal("0.9500")),
            _candidate(fallback_agent_id, "fallback-agent", Decimal("0.8000")),
        ),
        genome_signals=(signal,),
    )

    assert [match.agent.agent_id for match in result.matches] == [
        fallback_agent_id,
        observed_agent_id,
    ]
    assert result.matches[1].breakdown.expertise == Decimal("0.2000")
    assert result.matches[1].explanation[-1] == "Genome evidence adjusted capability fit."


def test_no_genome_signal_preserves_the_matcher_result() -> None:
    first_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    second_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000004")
    request = AgentMatchingRequest(
        project_id=uuid.uuid4(),
        workstream=_workstream(),
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=(
            AgentCostEstimate(agent_id=first_agent_id, normalized_cost=Decimal("0.2000")),
            AgentCostEstimate(agent_id=second_agent_id, normalized_cost=Decimal("0.2000")),
        ),
    )
    candidates = (
        _candidate(first_agent_id, "first-agent", Decimal("0.9000")),
        _candidate(second_agent_id, "second-agent", Decimal("0.7000")),
    )

    result = AgentGenomeManagerSignalMatcher().match(
        request,
        candidates=candidates,
        genome_signals=(),
    )

    assert [match.agent.agent_id for match in result.matches] == [first_agent_id, second_agent_id]
    assert all(
        "Genome evidence adjusted capability fit." not in match.explanation
        for match in result.matches
    )


def test_signal_cannot_make_missing_capability_or_permission_eligible() -> None:
    agent_id = uuid.UUID("00000000-0000-0000-0000-000000000005")
    request = AgentMatchingRequest(
        project_id=uuid.uuid4(),
        workstream=_workstream(),
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=(AgentCostEstimate(agent_id=agent_id, normalized_cost=Decimal("0.2000")),),
    )
    candidate = _candidate(agent_id, "ineligible-agent", Decimal("0.9000")).model_copy(
        update={"capabilities": (), "active_permissions": ()}
    )
    signal = AgentGenomeManagerSignal(
        agent_id=agent_id,
        genome_version_id=uuid.uuid4(),
        capabilities=(
            AgentGenomeCapabilitySignal(
                capability_key="backend-engineering",
                score=Decimal("1.0000"),
                confidence=Decimal("1.0000"),
            ),
        ),
    )

    result = AgentGenomeManagerSignalMatcher().match(
        request,
        candidates=(candidate,),
        genome_signals=(signal,),
    )

    assert result.matches == ()
    assert result.rejections[0].agent_id == agent_id
    assert result.rejections[0].reasons == (
        "Missing required capabilities: backend-engineering, payment-security.",
        "Missing required permissions: filesystem.read.",
    )


def test_duplicate_or_unknown_genome_signals_are_rejected() -> None:
    known_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000006")
    unknown_agent_id = uuid.UUID("00000000-0000-0000-0000-000000000007")
    request = AgentMatchingRequest(
        project_id=uuid.uuid4(),
        workstream=_workstream(),
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=(
            AgentCostEstimate(agent_id=known_agent_id, normalized_cost=Decimal("0.2000")),
        ),
    )
    known_signal = AgentGenomeManagerSignal(
        agent_id=known_agent_id,
        genome_version_id=uuid.uuid4(),
        capabilities=(),
    )
    unknown_signal = known_signal.model_copy(update={"agent_id": unknown_agent_id})
    matcher = AgentGenomeManagerSignalMatcher()

    with pytest.raises(ValueError, match="unique agents"):
        matcher.match(
            request,
            candidates=(_candidate(known_agent_id, "known-agent", Decimal("0.9000")),),
            genome_signals=(known_signal, known_signal),
        )
    with pytest.raises(ValueError, match="supplied candidates"):
        matcher.match(
            request,
            candidates=(_candidate(known_agent_id, "known-agent", Decimal("0.9000")),),
            genome_signals=(unknown_signal,),
        )
