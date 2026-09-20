"""Strict provider-neutral contracts for immutable Agent Genome evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type EvidenceMetadataValue = str | int | bool
type EvidenceMetadata = tuple[tuple[str, EvidenceMetadataValue], ...]

_ALLOWED_METADATA_KEYS = frozenset(
    {"approval_kind", "head_sha", "iteration", "model", "provider", "usage_kind"}
)
_MAX_METADATA_ITEMS = 8
_MAX_METADATA_STRING_LENGTH = 255
_MAX_METADATA_INTEGER = 10_000_000_000


class EvidenceSourceType(StrEnum):
    """Closed trusted persistence sources accepted by GEN-2."""

    AGENT_RUN = "AGENT_RUN"
    PULL_REQUEST_REVIEW = "PULL_REQUEST_REVIEW"
    QA_APPROVAL = "QA_APPROVAL"
    SECURITY_APPROVAL = "SECURITY_APPROVAL"
    USAGE_RECORD = "USAGE_RECORD"


class EvidenceSignal(StrEnum):
    """Observed facts recorded without calculating a score."""

    RUN_OUTCOME = "RUN_OUTCOME"
    REVIEW_OUTCOME = "REVIEW_OUTCOME"
    QA_OUTCOME = "QA_OUTCOME"
    SECURITY_OUTCOME = "SECURITY_OUTCOME"
    TOTAL_TOKENS = "TOTAL_TOKENS"
    WALL_CLOCK_DURATION = "WALL_CLOCK_DURATION"
    TOOL_CALL_COUNT = "TOOL_CALL_COUNT"
    CPU_DURATION = "CPU_DURATION"
    GPU_DURATION = "GPU_DURATION"
    PROVIDER_COST = "PROVIDER_COST"


class EvidenceOutcome(StrEnum):
    """Normalized source outcome without weighting or interpretation."""

    OBSERVED = "OBSERVED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class EvidenceUnit(StrEnum):
    """Closed units for numeric evidence values."""

    TOKENS = "TOKENS"
    MILLISECONDS = "MILLISECONDS"
    COUNT = "COUNT"
    PROVIDER_CURRENCY = "PROVIDER_CURRENCY"


def filter_evidence_metadata(values: Mapping[str, object]) -> EvidenceMetadata:
    """Return only bounded allowlisted scalar metadata, detached from the input."""
    filtered: list[tuple[str, EvidenceMetadataValue]] = []
    for key in sorted(_ALLOWED_METADATA_KEYS.intersection(values)):
        value = values[key]
        if (
            isinstance(value, bool)
            or type(value) is int
            and 0 <= value <= _MAX_METADATA_INTEGER
            or isinstance(value, str)
            and 1 <= len(value) <= _MAX_METADATA_STRING_LENGTH
            and value == value.strip()
            and all(ord(character) >= 32 for character in value)
        ):
            filtered.append((key, value))
        if len(filtered) == _MAX_METADATA_ITEMS:
            break
    return tuple(filtered)


class GenomeEvidenceDraft(BaseModel):
    """One validated evidence row ready for provenance-checked persistence."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    agent_id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    run_id: UUID | None = None
    source_type: EvidenceSourceType
    source_id: UUID
    signal: EvidenceSignal
    outcome: EvidenceOutcome
    numeric_value: Annotated[
        Decimal | None,
        Field(ge=Decimal("0"), max_digits=20, decimal_places=8),
    ] = None
    unit: EvidenceUnit | None = None
    metadata: EvidenceMetadata = ()
    observed_at: datetime

    @field_validator("metadata", mode="before")
    @classmethod
    def sanitize_metadata(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return filter_evidence_metadata(value)
        if isinstance(value, (tuple, list)):
            try:
                return filter_evidence_metadata(dict(value))
            except (TypeError, ValueError):
                raise ValueError("evidence metadata is invalid") from None
        raise ValueError("evidence metadata is invalid")

    @model_validator(mode="after")
    def require_consistent_scope_and_value(self) -> Self:
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task evidence requires project scope")
        if (self.numeric_value is None) != (self.unit is None):
            raise ValueError("numeric evidence requires both value and unit")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("evidence observation time must be timezone-aware")
        allowed_signals = {
            EvidenceSourceType.AGENT_RUN: {EvidenceSignal.RUN_OUTCOME},
            EvidenceSourceType.PULL_REQUEST_REVIEW: {EvidenceSignal.REVIEW_OUTCOME},
            EvidenceSourceType.QA_APPROVAL: {EvidenceSignal.QA_OUTCOME},
            EvidenceSourceType.SECURITY_APPROVAL: {EvidenceSignal.SECURITY_OUTCOME},
            EvidenceSourceType.USAGE_RECORD: {
                EvidenceSignal.TOTAL_TOKENS,
                EvidenceSignal.WALL_CLOCK_DURATION,
                EvidenceSignal.TOOL_CALL_COUNT,
                EvidenceSignal.CPU_DURATION,
                EvidenceSignal.GPU_DURATION,
                EvidenceSignal.PROVIDER_COST,
            },
        }
        if self.signal not in allowed_signals[self.source_type]:
            raise ValueError("evidence signal does not match source type")
        if self.source_type is EvidenceSourceType.AGENT_RUN and (
            self.run_id is None or self.run_id != self.source_id
        ):
            raise ValueError("agent run evidence requires exact run provenance")
        allowed_outcomes = {
            EvidenceSourceType.AGENT_RUN: {
                EvidenceOutcome.SUCCEEDED,
                EvidenceOutcome.FAILED,
                EvidenceOutcome.CANCELLED,
                EvidenceOutcome.TIMED_OUT,
            },
            EvidenceSourceType.PULL_REQUEST_REVIEW: {
                EvidenceOutcome.APPROVED,
                EvidenceOutcome.CHANGES_REQUESTED,
            },
            EvidenceSourceType.QA_APPROVAL: {
                EvidenceOutcome.PASSED,
                EvidenceOutcome.REJECTED,
                EvidenceOutcome.BLOCKED,
            },
            EvidenceSourceType.SECURITY_APPROVAL: {
                EvidenceOutcome.PASSED,
                EvidenceOutcome.REJECTED,
                EvidenceOutcome.BLOCKED,
            },
            EvidenceSourceType.USAGE_RECORD: {EvidenceOutcome.OBSERVED},
        }
        if self.outcome not in allowed_outcomes[self.source_type]:
            raise ValueError("evidence outcome does not match source type")
        numeric_source = self.source_type is EvidenceSourceType.USAGE_RECORD
        if numeric_source != (self.numeric_value is not None):
            raise ValueError("only usage evidence carries numeric values")
        if self.numeric_value is not None:
            expected_units = {
                EvidenceSignal.TOTAL_TOKENS: EvidenceUnit.TOKENS,
                EvidenceSignal.WALL_CLOCK_DURATION: EvidenceUnit.MILLISECONDS,
                EvidenceSignal.TOOL_CALL_COUNT: EvidenceUnit.COUNT,
                EvidenceSignal.CPU_DURATION: EvidenceUnit.MILLISECONDS,
                EvidenceSignal.GPU_DURATION: EvidenceUnit.MILLISECONDS,
                EvidenceSignal.PROVIDER_COST: EvidenceUnit.PROVIDER_CURRENCY,
            }
            if self.unit is not expected_units[self.signal]:
                raise ValueError("numeric evidence unit does not match signal")
            if (
                self.signal
                in {
                    EvidenceSignal.TOTAL_TOKENS,
                    EvidenceSignal.TOOL_CALL_COUNT,
                }
                and self.numeric_value != self.numeric_value.to_integral_value()
            ):
                raise ValueError("token and count evidence must be integral")
        return self
