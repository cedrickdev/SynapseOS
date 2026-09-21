"""Tests for Trust-aware deterministic AI Manager selection."""

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
from core.manager import AgentTrustManagerSignal, AgentWorkload, TrustAwareManagerSelector
from core.trust import TrustClass, TrustGovernorSignal, TrustGovernorSignalDisposition


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


def test_restricted_trust_signal_cannot_be_selected() -> None:
    """A restrictive Trust signal excludes its agent before capacity selection."""
    restricted_agent_id = UUID("00000000-0000-0000-0000-000000000001")
    fallback_agent_id = UUID("00000000-0000-0000-0000-000000000002")
    result = AgentMatchingResult.model_construct(
        workstream_id="backend",
        matches=(_match(restricted_agent_id, "restricted"), _match(fallback_agent_id, "fallback")),
        rejections=(),
    )

    selection = TrustAwareManagerSelector().select(
        result,
        trust_signals=(
            AgentTrustManagerSignal(
                agent_id=restricted_agent_id,
                signal=TrustGovernorSignal(
                    overall_score=Decimal("20"),
                    trust_class=TrustClass.LOW,
                    trust_algorithm_version="trust-v1",
                    disposition=TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED,
                    requires_governor_recomputation=True,
                    critical_event_id=UUID("00000000-0000-0000-0000-000000000003"),
                ),
            ),
            AgentTrustManagerSignal(
                agent_id=fallback_agent_id,
                signal=TrustGovernorSignal(
                    overall_score=Decimal("80"),
                    trust_class=TrustClass.STANDARD,
                    trust_algorithm_version="trust-v1",
                    disposition=TrustGovernorSignalDisposition.NEUTRAL,
                    requires_governor_recomputation=False,
                    critical_event_id=None,
                ),
            ),
        ),
        workloads=(
            AgentWorkload(
                agent_id=restricted_agent_id,
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
        ),
    )

    assert selection.selected_agent_id == fallback_agent_id
