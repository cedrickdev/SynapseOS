"""Deterministic classification of trusted Agent Genome failure evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.genome.evidence import EvidenceOutcome, EvidenceSignal, EvidenceSourceType
from core.genome.types import GenomeFailureSeverity

_MAX_EVIDENCE = 256

_FAILURE_PATTERNS = {
    (EvidenceSourceType.AGENT_RUN, EvidenceOutcome.FAILED): (
        "agent_run.failed",
        GenomeFailureSeverity.MEDIUM,
    ),
    (EvidenceSourceType.AGENT_RUN, EvidenceOutcome.TIMED_OUT): (
        "agent_run.timed_out",
        GenomeFailureSeverity.HIGH,
    ),
    (EvidenceSourceType.PULL_REQUEST_REVIEW, EvidenceOutcome.CHANGES_REQUESTED): (
        "review.changes_requested",
        GenomeFailureSeverity.MEDIUM,
    ),
    (EvidenceSourceType.QA_APPROVAL, EvidenceOutcome.REJECTED): (
        "qa.rejected",
        GenomeFailureSeverity.HIGH,
    ),
    (EvidenceSourceType.QA_APPROVAL, EvidenceOutcome.BLOCKED): (
        "qa.blocked",
        GenomeFailureSeverity.HIGH,
    ),
    (EvidenceSourceType.SECURITY_APPROVAL, EvidenceOutcome.REJECTED): (
        "security.rejected",
        GenomeFailureSeverity.CRITICAL,
    ),
    (EvidenceSourceType.SECURITY_APPROVAL, EvidenceOutcome.BLOCKED): (
        "security.blocked",
        GenomeFailureSeverity.CRITICAL,
    ),
}


class FailurePatternObservation(BaseModel):
    """Minimal immutable trusted observation accepted by the analyzer."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    evidence_id: UUID
    agent_id: UUID
    source_type: EvidenceSourceType
    signal: EvidenceSignal
    outcome: EvidenceOutcome
    observed_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("failure evidence time must be timezone-aware")
        return self


class FailurePatternRequest(BaseModel):
    """Bounded request to analyze one agent's trusted evidence set."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: UUID
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=_MAX_EVIDENCE)]

    @model_validator(mode="after")
    def require_unique_evidence(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("failure evidence identifiers must be unique")
        return self


class FailurePatternResult(BaseModel):
    """One reproducible grouped failure pattern."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    agent_id: UUID
    pattern_key: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$", max_length=128)]
    count: Annotated[int, Field(gt=0, le=_MAX_EVIDENCE)]
    severity: GenomeFailureSeverity
    last_seen_at: datetime
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=_MAX_EVIDENCE)]


class FailurePatternAnalyzer:
    """Group only known trusted failure outcomes; no LLM interpretation is used."""

    def analyze(
        self, observations: tuple[FailurePatternObservation, ...]
    ) -> tuple[FailurePatternResult, ...]:
        if type(observations) is not tuple or len(observations) > _MAX_EVIDENCE:
            raise ValueError("failure observations must be a bounded tuple")
        if any(type(item) is not FailurePatternObservation for item in observations):
            raise TypeError("failure observations must be canonical")
        agent_ids = {item.agent_id for item in observations}
        if len(agent_ids) > 1:
            raise ValueError("failure observations must belong to one agent")
        if len({item.evidence_id for item in observations}) != len(observations):
            raise ValueError("failure evidence identifiers must be unique")
        groups: dict[tuple[str, GenomeFailureSeverity], list[FailurePatternObservation]] = (
            defaultdict(list)
        )
        for item in observations:
            expected_signal = {
                EvidenceSourceType.AGENT_RUN: EvidenceSignal.RUN_OUTCOME,
                EvidenceSourceType.PULL_REQUEST_REVIEW: EvidenceSignal.REVIEW_OUTCOME,
                EvidenceSourceType.QA_APPROVAL: EvidenceSignal.QA_OUTCOME,
                EvidenceSourceType.SECURITY_APPROVAL: EvidenceSignal.SECURITY_OUTCOME,
            }.get(item.source_type)
            if expected_signal is not None and item.signal is not expected_signal:
                raise ValueError("failure evidence signal does not match its source")
            pattern = _FAILURE_PATTERNS.get((item.source_type, item.outcome))
            if pattern is not None:
                groups[pattern].append(item)
        if not agent_ids:
            return ()
        agent_id = next(iter(agent_ids))
        return tuple(
            FailurePatternResult(
                agent_id=agent_id,
                pattern_key=pattern_key,
                count=len(items),
                severity=severity,
                last_seen_at=max(item.observed_at for item in items),
                evidence_ids=tuple(
                    item.evidence_id
                    for item in sorted(
                        items, key=lambda value: (value.observed_at, value.evidence_id)
                    )
                ),
            )
            for (pattern_key, severity), items in sorted(groups.items())
        )
