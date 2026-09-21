"""Tests for Genome-aware deterministic AI Manager selection."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from core.agent_registry import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentCostEstimate,
    AgentGenomeCapabilitySignal,
    AgentGenomeManagerSignal,
    AgentMatchingRequest,
)
from core.domain_decomposition import DomainWorkstream, WorkstreamScope
from core.enums import AgentSeniority, AgentStatus, Permission, ToolRiskLevel
from core.manager import AgentWorkload, GenomeAwareManagerSelector


def _candidate(agent_id: UUID, slug: str, expertise: Decimal) -> AgentCandidate:
    return AgentCandidate(
        agent_id=agent_id,
        slug=slug,
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
        autonomy_level=3,
        reputation=Decimal("0.8000"),
        reliability=Decimal("0.8000"),
        capabilities=(AgentCapabilitySnapshot(name="backend-engineering", expertise=expertise),),
        active_permissions=(Permission.FILESYSTEM_READ,),
    )


def test_genome_evidence_can_reorder_capacity_available_candidates() -> None:
    observed_agent_id = UUID("00000000-0000-0000-0000-000000000001")
    fallback_agent_id = UUID("00000000-0000-0000-0000-000000000002")
    request = AgentMatchingRequest(
        project_id=uuid4(),
        workstream=DomainWorkstream(
            id="backend",
            name="Backend",
            scope_kind=WorkstreamScope.DOMAIN,
            purpose="Own backend delivery.",
            source_domains=("Backend",),
            responsibilities=("Implement services",),
            required_capabilities=("backend-engineering",),
            dependencies=(),
        ),
        required_permissions=(Permission.FILESYSTEM_READ,),
        minimum_seniority=AgentSeniority.ENGINEER,
        risk_level=ToolRiskLevel.HIGH,
        cost_estimates=(
            AgentCostEstimate(agent_id=observed_agent_id, normalized_cost=Decimal("0.2000")),
            AgentCostEstimate(agent_id=fallback_agent_id, normalized_cost=Decimal("0.2000")),
        ),
    )
    genome_signal = AgentGenomeManagerSignal(
        agent_id=observed_agent_id,
        genome_version_id=uuid4(),
        capabilities=(
            AgentGenomeCapabilitySignal(
                capability_key="backend-engineering",
                score=Decimal("0.2000"),
                confidence=Decimal("1.0000"),
            ),
        ),
    )
    workloads = (
        AgentWorkload(
            agent_id=observed_agent_id,
            active_tasks=0,
            queued_tasks=0,
            estimated_remaining_seconds=0,
            capacity_score=Decimal("1"),
            updated_at=datetime.now(UTC),
        ),
        AgentWorkload(
            agent_id=fallback_agent_id,
            active_tasks=0,
            queued_tasks=0,
            estimated_remaining_seconds=0,
            capacity_score=Decimal("1"),
            updated_at=datetime.now(UTC),
        ),
    )

    selection = GenomeAwareManagerSelector().select(
        request,
        candidates=(
            _candidate(observed_agent_id, "observed", Decimal("0.9500")),
            _candidate(fallback_agent_id, "fallback", Decimal("0.8000")),
        ),
        genome_signals=(genome_signal,),
        workloads=workloads,
    )

    assert selection.selected_agent_id == fallback_agent_id
    assert selection.alternative_agent_ids == (observed_agent_id,)
