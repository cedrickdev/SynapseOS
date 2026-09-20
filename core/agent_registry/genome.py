"""Read-only Agent Genome signals for deterministic manager selection."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.agent_registry.matcher import AgentMatcher
from core.agent_registry.types import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentMatchingRequest,
    AgentMatchingResult,
)

_MAX_SIGNALS = 100
_MAX_CAPABILITIES = 64
_SCORE = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)]
_IDENTIFIER = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class _ImmutableGenomeSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentGenomeCapabilitySignal(_ImmutableGenomeSignal):
    """One evidence-backed capability measure from an active Genome version."""

    capability_key: _IDENTIFIER
    score: _SCORE
    confidence: _SCORE


class AgentGenomeManagerSignal(_ImmutableGenomeSignal):
    """Bounded active Genome signal that a manager may use for one candidate."""

    agent_id: uuid.UUID
    genome_version_id: uuid.UUID
    capabilities: Annotated[
        tuple[AgentGenomeCapabilitySignal, ...], Field(max_length=_MAX_CAPABILITIES)
    ]

    @field_validator("capabilities", mode="before")
    @classmethod
    def copy_capabilities(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_capabilities(self) -> Self:
        keys = tuple(capability.capability_key.casefold() for capability in self.capabilities)
        if len(keys) != len(set(keys)):
            raise ValueError("Genome capability signals must be unique")
        return self


class AgentGenomeManagerSignalMatcher:
    """Apply conservative evidence signals before read-only candidate ranking."""

    def __init__(self, matcher: AgentMatcher | None = None) -> None:
        self._matcher = matcher or AgentMatcher()

    def match(
        self,
        request: AgentMatchingRequest,
        *,
        candidates: Sequence[AgentCandidate],
        genome_signals: Sequence[AgentGenomeManagerSignal],
    ) -> AgentMatchingResult:
        canonical_signals = _canonical_signals(genome_signals)
        candidate_ids = {candidate.agent_id for candidate in candidates}
        if any(signal.agent_id not in candidate_ids for signal in canonical_signals):
            raise ValueError("Genome signals must reference supplied candidates")
        signals_by_agent = {signal.agent_id: signal for signal in canonical_signals}
        adjusted_ids: set[uuid.UUID] = set()
        enriched_candidates = tuple(
            _enrich_candidate(candidate, signals_by_agent.get(candidate.agent_id), adjusted_ids)
            for candidate in candidates
        )
        result = self._matcher.match(request, enriched_candidates)
        return result.model_copy(
            update={
                "matches": tuple(
                    match.model_copy(
                        update={
                            "explanation": match.explanation
                            + ("Genome evidence adjusted capability fit.",)
                        }
                    )
                    if match.agent.agent_id in adjusted_ids
                    else match
                    for match in result.matches
                )
            }
        )


def _canonical_signals(
    signals: Sequence[AgentGenomeManagerSignal],
) -> tuple[AgentGenomeManagerSignal, ...]:
    if not isinstance(signals, (list, tuple)) or len(signals) > _MAX_SIGNALS:
        raise ValueError("Genome signals must be a bounded sequence")
    retained = tuple(
        AgentGenomeManagerSignal.model_validate(signal.model_dump(mode="python"), strict=True)
        if type(signal) is AgentGenomeManagerSignal
        else _reject_signal()
        for signal in signals
    )
    identifiers = tuple(signal.agent_id for signal in retained)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Genome signals must identify unique agents")
    return retained


def _reject_signal() -> AgentGenomeManagerSignal:
    raise ValueError("invalid Genome signal")


def _enrich_candidate(
    candidate: AgentCandidate,
    signal: AgentGenomeManagerSignal | None,
    adjusted_ids: set[uuid.UUID],
) -> AgentCandidate:
    if signal is None:
        return candidate
    metrics = {item.capability_key.casefold(): item for item in signal.capabilities}
    capabilities: list[AgentCapabilitySnapshot] = []
    adjusted = False
    for capability in candidate.capabilities:
        metric = metrics.get(capability.name.casefold())
        if metric is None:
            capabilities.append(capability)
            continue
        evidence_bound = metric.score * metric.confidence
        expertise = min(capability.expertise, evidence_bound)
        adjusted = adjusted or expertise != capability.expertise
        capabilities.append(AgentCapabilitySnapshot(name=capability.name, expertise=expertise))
    if not adjusted:
        return candidate
    adjusted_ids.add(candidate.agent_id)
    return candidate.model_copy(update={"capabilities": tuple(capabilities)})
