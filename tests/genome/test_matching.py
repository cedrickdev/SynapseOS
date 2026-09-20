"""Unit tests for deterministic Genome capability matching."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from core.genome import (
    GenomeCapabilityCandidate,
    GenomeCapabilityMatcher,
    GenomeCapabilityMatchingRequest,
    GenomeCapabilityMetricSnapshot,
)


def _candidate(
    *,
    capabilities: tuple[str, ...],
    metrics: tuple[tuple[str, str, str], ...],
) -> GenomeCapabilityCandidate:
    return GenomeCapabilityCandidate(
        agent_id=uuid4(),
        available=True,
        declared_capabilities=capabilities,
        metrics=tuple(
            GenomeCapabilityMetricSnapshot(
                capability_key=key,
                score=Decimal(score),
                confidence=Decimal(confidence),
            )
            for key, score, confidence in metrics
        ),
    )


def test_matcher_ranks_by_conservative_capability_fit() -> None:
    strongest = _candidate(
        capabilities=("python", "postgresql"),
        metrics=(("python", "0.9000", "0.9000"), ("postgresql", "0.8000", "0.8000")),
    )
    weaker = _candidate(
        capabilities=("python", "postgresql"),
        metrics=(("python", "0.9500", "0.4000"), ("postgresql", "0.7000", "0.4000")),
    )

    result = GenomeCapabilityMatcher().match(
        GenomeCapabilityMatchingRequest(
            genome_version_ids=(uuid4(), uuid4()),
            required_capabilities=("python", "postgresql"),
            limit=10,
        ),
        (weaker, strongest),
    )

    assert [item.agent_id for item in result.matches] == [strongest.agent_id, weaker.agent_id]
    assert result.matches[0].score == Decimal("0.7250")
    assert result.matches[0].matched_capabilities == ("postgresql", "python")
    assert result.matches[0].missing_capabilities == ()


def test_matcher_rejects_missing_declaration_or_evidence() -> None:
    undeclared = _candidate(capabilities=("python",), metrics=(("python", "0.9000", "0.9000"),))
    no_evidence = _candidate(
        capabilities=("python", "postgresql"), metrics=(("python", "0.9000", "0.9000"),)
    )

    result = GenomeCapabilityMatcher().match(
        GenomeCapabilityMatchingRequest(
            genome_version_ids=(uuid4(), uuid4()),
            required_capabilities=("python", "postgresql"),
        ),
        (undeclared, no_evidence),
    )

    assert result.matches == ()
    reasons = {item.agent_id: item.reasons for item in result.rejections}
    assert reasons[undeclared.agent_id] == ("Missing declared capabilities: postgresql.",)
    assert reasons[no_evidence.agent_id] == ("Missing Genome evidence: postgresql.",)


def test_matcher_is_order_independent_and_bounded() -> None:
    first = _candidate(capabilities=("python",), metrics=(("python", "0.8000", "0.8000"),))
    second = _candidate(capabilities=("python",), metrics=(("python", "0.7000", "0.9000"),))
    request = GenomeCapabilityMatchingRequest(
        genome_version_ids=(uuid4(), uuid4()), required_capabilities=("python",), limit=1
    )

    forward = GenomeCapabilityMatcher().match(request, (first, second))
    reverse = GenomeCapabilityMatcher().match(request, (second, first))

    assert forward.matches[0].agent_id == reverse.matches[0].agent_id
    assert len(forward.matches) == 1
