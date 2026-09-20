"""PostgreSQL-backed append-only Agent Genome failure-pattern tracking."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.genome import (
    FailurePatternAnalyzer,
    FailurePatternObservation,
    FailurePatternRequest,
    FailurePatternResult,
)
from infrastructure.database.models import AgentFailurePattern, AgentGenomeEvidence


class AgentFailurePatternUnavailableError(RuntimeError):
    """Sanitized persistence failure while loading failure evidence."""

    def __init__(self) -> None:
        super().__init__("Agent failure-pattern tracking is unavailable.")


class AgentFailurePatternService:
    """Analyze trusted evidence and append immutable aggregate observations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, request: FailurePatternRequest) -> tuple[AgentFailurePattern, ...]:
        if type(request) is not FailurePatternRequest:
            raise TypeError("failure-pattern request must be canonical")
        try:
            evidence = tuple(
                self._session.scalars(
                    select(AgentGenomeEvidence)
                    .where(AgentGenomeEvidence.id.in_(request.evidence_ids))
                    .order_by(AgentGenomeEvidence.observed_at, AgentGenomeEvidence.id)
                )
            )
        except SQLAlchemyError:
            raise AgentFailurePatternUnavailableError() from None
        if len(evidence) != len(request.evidence_ids):
            raise ValueError("all requested failure evidence must exist")
        if any(item.agent_id != request.agent_id for item in evidence):
            raise ValueError("all failure evidence must belong to the requested agent")
        observations = tuple(
            FailurePatternObservation(
                evidence_id=item.id,
                agent_id=item.agent_id,
                source_type=item.source_type,
                signal=item.signal,
                outcome=item.outcome,
                observed_at=item.observed_at,
            )
            for item in evidence
        )
        results = FailurePatternAnalyzer().analyze(observations)
        patterns: list[AgentFailurePattern] = []
        for result in results:
            existing = self._find_existing(result)
            if existing is not None:
                patterns.append(existing)
                continue
            pattern = AgentFailurePattern(
                agent_id=result.agent_id,
                pattern_key=result.pattern_key,
                count=result.count,
                severity=result.severity,
                last_seen_at=result.last_seen_at,
                metadata_={
                    "evidence_ids": [str(evidence_id) for evidence_id in result.evidence_ids],
                    "pattern_source": "trusted_genome_evidence",
                },
            )
            self._session.add(pattern)
            patterns.append(pattern)
        return tuple(patterns)

    def _find_existing(self, result: FailurePatternResult) -> AgentFailurePattern | None:
        expected_ids = [str(evidence_id) for evidence_id in result.evidence_ids]
        candidates = tuple(
            self._session.scalars(
                select(AgentFailurePattern)
                .where(
                    AgentFailurePattern.agent_id == result.agent_id,
                    AgentFailurePattern.pattern_key == result.pattern_key,
                )
                .order_by(AgentFailurePattern.created_at.desc(), AgentFailurePattern.id.desc())
            )
        )
        return next(
            (
                candidate
                for candidate in candidates
                if candidate.metadata_.get("evidence_ids") == expected_ids
            ),
            None,
        )
