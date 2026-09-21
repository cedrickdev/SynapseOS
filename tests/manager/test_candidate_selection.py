"""Tests for deterministic AI Manager candidate selection."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from core.agent_registry import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentMatchingResult,
    AgentMatchScore,
    RankedAgentMatch,
)
from core.enums import AgentSeniority, AgentStatus, Permission
from core.manager import AgentWorkload, ManagerCandidateSelector


def _match(agent_id: UUID, slug: str) -> RankedAgentMatch:
    return RankedAgentMatch(
        agent=AgentCandidate(
            agent_id=agent_id,
            slug=slug,
            seniority=AgentSeniority.SENIOR,
            status=AgentStatus.AVAILABLE,
            autonomy_level=2,
            reputation=Decimal("0.8000"),
            reliability=Decimal("0.8000"),
            capabilities=(
                AgentCapabilitySnapshot(name="backend-engineering", expertise=Decimal("0.8")),
            ),
            active_permissions=(Permission.FILESYSTEM_READ,),
        ),
        score=Decimal("0.8"),
        breakdown=AgentMatchScore(
            expertise=Decimal("0.8"),
            reputation=Decimal("0.8"),
            reliability=Decimal("0.8"),
            seniority_fit=Decimal("0.8"),
            cost_efficiency=Decimal("0.8"),
        ),
        explanation=("Eligible.",),
    )


def test_selector_skips_an_overloaded_candidate_without_reordering_matches() -> None:
    first_agent_id = UUID("00000000-0000-0000-0000-000000000001")
    second_agent_id = UUID("00000000-0000-0000-0000-000000000002")
    matches = AgentMatchingResult(
        workstream_id="backend",
        matches=(_match(first_agent_id, "first"), _match(second_agent_id, "second")),
        rejections=(),
    )
    workloads = (
        AgentWorkload(
            agent_id=first_agent_id,
            active_tasks=1,
            queued_tasks=0,
            estimated_remaining_seconds=60,
            capacity_score=Decimal("0"),
            updated_at=datetime.now(UTC),
        ),
        AgentWorkload(
            agent_id=second_agent_id,
            active_tasks=0,
            queued_tasks=0,
            estimated_remaining_seconds=0,
            capacity_score=Decimal("1"),
            updated_at=datetime.now(UTC),
        ),
    )

    selection = ManagerCandidateSelector().select(matches, workloads)

    assert selection.selected_agent_id == second_agent_id
    assert selection.alternative_agent_ids == ()
