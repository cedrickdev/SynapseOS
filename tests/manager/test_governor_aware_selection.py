"""Tests for Governor-constrained AI Manager selection."""

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
from core.autonomy import AutonomyLevel
from core.autonomy.policy import PolicyReasonCode, PolicyRecommendation
from core.enums import AgentSeniority, AgentStatus, Permission
from core.manager import (
    AgentGovernorManagerRecommendation,
    AgentWorkload,
    GovernorAwareManagerSelector,
)


def _match(agent_id: UUID, slug: str) -> RankedAgentMatch:
    return RankedAgentMatch(
        agent=AgentCandidate(
            agent_id=agent_id,
            slug=slug,
            seniority=AgentSeniority.SENIOR,
            status=AgentStatus.AVAILABLE,
            autonomy_level=2,
            reputation=Decimal("0.8"),
            reliability=Decimal("0.8"),
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


def test_approval_gated_candidate_is_not_selected_automatically() -> None:
    gated_agent_id = UUID("00000000-0000-0000-0000-000000000001")
    bounded_agent_id = UUID("00000000-0000-0000-0000-000000000002")
    result = AgentMatchingResult(
        workstream_id="backend",
        matches=(_match(gated_agent_id, "gated"), _match(bounded_agent_id, "bounded")),
        rejections=(),
    )

    selection = GovernorAwareManagerSelector().select(
        result,
        recommendations=(
            AgentGovernorManagerRecommendation(
                agent_id=gated_agent_id,
                recommendation=PolicyRecommendation(
                    maximum_autonomy_level=AutonomyLevel.ACT_WITH_APPROVAL,
                    reason_codes=(PolicyReasonCode.APPROVAL_REQUIRED,),
                    policy_version="governor-v1",
                    approval_required=True,
                ),
            ),
            AgentGovernorManagerRecommendation(
                agent_id=bounded_agent_id,
                recommendation=PolicyRecommendation(
                    maximum_autonomy_level=AutonomyLevel.BOUNDED_AUTONOMY,
                    reason_codes=(PolicyReasonCode.RISK_CEILING,),
                    policy_version="governor-v1",
                ),
            ),
        ),
        workloads=(
            AgentWorkload(
                agent_id=gated_agent_id,
                active_tasks=0,
                queued_tasks=0,
                estimated_remaining_seconds=0,
                capacity_score=Decimal("1"),
                updated_at=datetime.now(UTC),
            ),
            AgentWorkload(
                agent_id=bounded_agent_id,
                active_tasks=0,
                queued_tasks=0,
                estimated_remaining_seconds=0,
                capacity_score=Decimal("1"),
                updated_at=datetime.now(UTC),
            ),
        ),
    )

    assert selection.selected_agent_id == bounded_agent_id
