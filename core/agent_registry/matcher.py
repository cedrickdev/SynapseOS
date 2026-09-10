"""Deterministic Phase 28 agent matching."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from core.agent_registry.types import (
    AgentCandidate,
    AgentMatchingRequest,
    AgentMatchingResult,
    AgentMatchScore,
    RankedAgentMatch,
    RejectedAgentMatch,
)
from core.enums import AgentSeniority, AgentStatus, ToolRiskLevel

_MAX_CANDIDATES = 100
_QUANTUM = Decimal("0.0001")
_EXPERTISE_WEIGHT = Decimal("0.35")
_REPUTATION_WEIGHT = Decimal("0.20")
_RELIABILITY_WEIGHT = Decimal("0.20")
_SENIORITY_WEIGHT = Decimal("0.10")
_COST_WEIGHT = Decimal("0.15")
_SENIORITY_RANK = {
    AgentSeniority.TRAINEE: 0,
    AgentSeniority.JUNIOR: 1,
    AgentSeniority.ENGINEER: 2,
    AgentSeniority.SENIOR: 3,
    AgentSeniority.STAFF: 4,
    AgentSeniority.PRINCIPAL: 5,
}
_RISK_AUTONOMY = {
    ToolRiskLevel.LOW: 0,
    ToolRiskLevel.MEDIUM: 1,
    ToolRiskLevel.HIGH: 2,
    ToolRiskLevel.CRITICAL: 3,
}


class AgentMatcher:
    """Rank trusted candidate snapshots without assigning or mutating agents."""

    def match(
        self,
        request: AgentMatchingRequest,
        candidates: Sequence[AgentCandidate],
    ) -> AgentMatchingResult:
        canonical_request = _canonical_request(request)
        canonical_candidates = _canonical_candidates(candidates)
        costs = {
            estimate.agent_id: estimate.normalized_cost
            for estimate in canonical_request.cost_estimates
        }
        matches: list[RankedAgentMatch] = []
        rejections: list[RejectedAgentMatch] = []

        for candidate in canonical_candidates:
            reasons = _rejection_reasons(canonical_request, candidate, costs)
            if reasons:
                rejections.append(RejectedAgentMatch(agent_id=candidate.agent_id, reasons=reasons))
                continue
            matches.append(_ranked_match(canonical_request, candidate, costs[candidate.agent_id]))

        matches.sort(key=lambda item: (-item.score, item.agent.agent_id.int))
        rejections.sort(key=lambda item: item.agent_id.int)
        return AgentMatchingResult(
            workstream_id=canonical_request.workstream.id,
            matches=tuple(matches[: canonical_request.limit]),
            rejections=tuple(rejections),
        )


def _canonical_request(request: AgentMatchingRequest) -> AgentMatchingRequest:
    if type(request) is not AgentMatchingRequest:
        raise ValueError("invalid agent matching request")
    return AgentMatchingRequest.model_validate(
        request.model_dump(mode="python", warnings=False),
        strict=True,
    )


def _canonical_candidates(candidates: Sequence[AgentCandidate]) -> tuple[AgentCandidate, ...]:
    if not isinstance(candidates, (list, tuple)) or len(candidates) > _MAX_CANDIDATES:
        raise ValueError("agent candidates must be a bounded sequence")
    retained = tuple(
        AgentCandidate.model_validate(
            candidate.model_dump(mode="python", warnings=False),
            strict=True,
        )
        if type(candidate) is AgentCandidate
        else _reject_candidate()
        for candidate in candidates
    )
    identifiers = tuple(candidate.agent_id for candidate in retained)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("agent candidates must be unique")
    return retained


def _reject_candidate() -> AgentCandidate:
    raise ValueError("invalid agent candidate")


def _rejection_reasons(
    request: AgentMatchingRequest,
    candidate: AgentCandidate,
    costs: dict[uuid.UUID, Decimal],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if candidate.status is not AgentStatus.AVAILABLE:
        reasons.append("Agent is not available.")

    available_capabilities = {capability.name.casefold() for capability in candidate.capabilities}
    missing_capabilities = sorted(
        required
        for required in request.workstream.required_capabilities
        if required.casefold() not in available_capabilities
    )
    if missing_capabilities:
        reasons.append(f"Missing required capabilities: {', '.join(missing_capabilities)}.")

    missing_permissions = sorted(
        (
            permission
            for permission in request.required_permissions
            if permission not in candidate.active_permissions
        ),
        key=lambda permission: permission.value,
    )
    if missing_permissions:
        reasons.append(
            "Missing required permissions: "
            + ", ".join(permission.value for permission in missing_permissions)
            + "."
        )

    if candidate.autonomy_level < _RISK_AUTONOMY[request.risk_level]:
        reasons.append(f"Autonomy level is below the {request.risk_level.value} risk requirement.")
    if _SENIORITY_RANK[candidate.seniority] < _SENIORITY_RANK[request.minimum_seniority]:
        reasons.append(f"Seniority is below the {request.minimum_seniority.value} requirement.")
    if candidate.agent_id not in costs:
        reasons.append("No task cost estimate was supplied.")
    return tuple(reasons)


def _ranked_match(
    request: AgentMatchingRequest,
    candidate: AgentCandidate,
    normalized_cost: Decimal,
) -> RankedAgentMatch:
    capabilities = {capability.name.casefold(): capability for capability in candidate.capabilities}
    expertise = _quantize(
        sum(
            (
                capabilities[name.casefold()].expertise
                for name in request.workstream.required_capabilities
            ),
            start=Decimal("0"),
        )
        / len(request.workstream.required_capabilities)
    )
    breakdown = AgentMatchScore(
        expertise=expertise,
        reputation=candidate.reputation,
        reliability=candidate.reliability,
        seniority_fit=_seniority_fit(candidate.seniority),
        cost_efficiency=_quantize(Decimal("1") - normalized_cost),
    )
    score = _quantize(
        breakdown.expertise * _EXPERTISE_WEIGHT
        + breakdown.reputation * _REPUTATION_WEIGHT
        + breakdown.reliability * _RELIABILITY_WEIGHT
        + breakdown.seniority_fit * _SENIORITY_WEIGHT
        + breakdown.cost_efficiency * _COST_WEIGHT
    )
    return RankedAgentMatch(
        agent=candidate,
        score=score,
        breakdown=breakdown,
        explanation=(
            "All required capabilities are active.",
            "All required permissions are active for the project scope.",
            f"Autonomy level satisfies {request.risk_level.value} risk.",
        ),
    )


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def _seniority_fit(seniority: AgentSeniority) -> Decimal:
    maximum_rank = max(_SENIORITY_RANK.values())
    return _quantize(Decimal(_SENIORITY_RANK[seniority]) / Decimal(maximum_rank))
