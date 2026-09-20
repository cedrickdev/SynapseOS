"""Deterministic capability ranking from persisted Agent Genome metrics."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
_SCORE = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=4)]
_MAX_CANDIDATES = 100
_QUANTUM = Decimal("0.0001")


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class GenomeCapabilityMetricSnapshot(_ImmutableModel):
    """One persisted capability score available to the matcher."""

    capability_key: Annotated[str, Field(pattern=_IDENTIFIER, max_length=128)]
    score: _SCORE
    confidence: _SCORE


class GenomeCapabilityCandidate(_ImmutableModel):
    """Bounded read-only candidate snapshot for Genome matching."""

    agent_id: uuid.UUID
    available: bool
    declared_capabilities: Annotated[tuple[str, ...], Field(max_length=64)]
    metrics: Annotated[tuple[GenomeCapabilityMetricSnapshot, ...], Field(max_length=64)]

    @model_validator(mode="after")
    def require_unique_capabilities(self) -> Self:
        declared = tuple(item.casefold() for item in self.declared_capabilities)
        measured = tuple(item.capability_key.casefold() for item in self.metrics)
        if len(declared) != len(set(declared)):
            raise ValueError("declared capabilities must be unique")
        if len(measured) != len(set(measured)):
            raise ValueError("Genome metrics must be unique")
        return self


class GenomeCapabilityMatchingRequest(_ImmutableModel):
    """Explicit bounded requirements for one Genome ranking decision."""

    genome_version_ids: Annotated[tuple[uuid.UUID, ...], Field(min_length=1, max_length=100)]
    required_capabilities: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    limit: Annotated[int, Field(ge=1, le=100)] = 10

    @model_validator(mode="after")
    def require_unique_requirements(self) -> Self:
        if len(set(self.genome_version_ids)) != len(self.genome_version_ids):
            raise ValueError("Genome version identifiers must be unique")
        normalized = tuple(item.casefold() for item in self.required_capabilities)
        if len(normalized) != len(set(normalized)):
            raise ValueError("required capabilities must be unique")
        return self


class RankedGenomeAgent(_ImmutableModel):
    """One ranked eligible Genome candidate with explainable fit."""

    agent_id: uuid.UUID
    score: _SCORE
    matched_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]


class RejectedGenomeAgent(_ImmutableModel):
    """One candidate excluded from Genome ranking with bounded reasons."""

    agent_id: uuid.UUID
    reasons: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]


class GenomeCapabilityMatchingResult(_ImmutableModel):
    """Read-only ranking result with deterministic matches and rejections."""

    matches: Annotated[tuple[RankedGenomeAgent, ...], Field(max_length=_MAX_CANDIDATES)]
    rejections: Annotated[tuple[RejectedGenomeAgent, ...], Field(max_length=_MAX_CANDIDATES)]


class GenomeCapabilityMatcher:
    """Rank candidates by average score adjusted by measured confidence."""

    def match(
        self,
        request: GenomeCapabilityMatchingRequest,
        candidates: tuple[GenomeCapabilityCandidate, ...],
    ) -> GenomeCapabilityMatchingResult:
        if type(request) is not GenomeCapabilityMatchingRequest:
            raise TypeError("matching request must be canonical")
        if type(candidates) is not tuple or len(candidates) > _MAX_CANDIDATES:
            raise ValueError("Genome candidates must be a bounded tuple")
        if any(type(candidate) is not GenomeCapabilityCandidate for candidate in candidates):
            raise TypeError("Genome candidates must be canonical")
        if len({candidate.agent_id for candidate in candidates}) != len(candidates):
            raise ValueError("Genome candidates must be unique")

        matches: list[RankedGenomeAgent] = []
        rejections: list[RejectedGenomeAgent] = []
        required = tuple(sorted(request.required_capabilities))
        for candidate in candidates:
            reasons = self._rejection_reasons(candidate, required)
            if reasons:
                rejections.append(RejectedGenomeAgent(agent_id=candidate.agent_id, reasons=reasons))
                continue
            metrics = {metric.capability_key: metric for metric in candidate.metrics}
            score = _quantize(
                sum(
                    (metrics[key].score * metrics[key].confidence for key in required),
                    Decimal("0"),
                )
                / Decimal(len(required))
            )
            matches.append(
                RankedGenomeAgent(
                    agent_id=candidate.agent_id,
                    score=score,
                    matched_capabilities=required,
                    missing_capabilities=(),
                )
            )
        matches.sort(key=lambda item: (-item.score, item.agent_id.int))
        rejections.sort(key=lambda item: item.agent_id.int)
        return GenomeCapabilityMatchingResult(
            matches=tuple(matches[: request.limit]),
            rejections=tuple(rejections),
        )

    @staticmethod
    def _rejection_reasons(
        candidate: GenomeCapabilityCandidate, required: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not candidate.available:
            return ("Agent is not available.",)
        declared = {item.casefold() for item in candidate.declared_capabilities}
        missing_declared = tuple(key for key in required if key.casefold() not in declared)
        if missing_declared:
            return (f"Missing declared capabilities: {', '.join(missing_declared)}.",)
        measured = {item.capability_key.casefold() for item in candidate.metrics}
        missing_evidence = tuple(key for key in required if key.casefold() not in measured)
        if missing_evidence:
            return (f"Missing Genome evidence: {', '.join(missing_evidence)}.",)
        return ()


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
