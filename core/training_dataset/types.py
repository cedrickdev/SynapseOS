"""Immutable contracts for future training datasets."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text = Annotated[str, Field(min_length=1, max_length=16_384)]
Score = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
]


class TrainingUsage(StrEnum):
    """Explicit future uses authorized by the data owner."""

    FINE_TUNING = "fine_tuning"
    PREFERENCE_LEARNING = "preference_learning"


class DatasetExclusionReason(StrEnum):
    """Sanitized reason for excluding an experience from a dataset."""

    NOT_VALIDATED = "NOT_VALIDATED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    SECRET_DETECTED = "SECRET_DETECTED"
    PII_DETECTED = "PII_DETECTED"


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ExperienceProvenance(_ImmutableModel):
    """Traceable evidence proving where one validated experience came from."""

    project_id: Identifier
    source_event_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]
    validated_by: Identifier
    validation_event_id: Identifier
    collected_at: datetime

    @field_validator("source_event_ids", mode="before")
    @classmethod
    def copy_event_ids(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_valid_provenance(self) -> Self:
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("source events must be unique")
        if self.collected_at.tzinfo is None or self.collected_at.utcoffset() is None:
            raise ValueError("collection time must be timezone-aware")
        return self


class TrainingConsent(_ImmutableModel):
    """Data-owner authorization attached to every exported record."""

    authorized: bool
    data_owner_id: Identifier
    consent_reference: Identifier
    allowed_uses: Annotated[tuple[TrainingUsage, ...], Field(max_length=2)]

    @field_validator("allowed_uses", mode="before")
    @classmethod
    def copy_allowed_uses(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_consistent_authorization(self) -> Self:
        if len(self.allowed_uses) != len(set(self.allowed_uses)):
            raise ValueError("allowed uses must be unique")
        if not self.authorized and self.allowed_uses:
            raise ValueError("unauthorized consent cannot grant training uses")
        return self


class ValidatedExperience(_ImmutableModel):
    """One bounded candidate experience supplied explicitly to the pipeline."""

    experience_id: Identifier
    validated: bool
    prompt_context: Text
    decision: Text
    alternatives: Annotated[tuple[Text, ...], Field(max_length=16)] = ()
    result: Text
    review: Text | None = None
    user_feedback: Text | None = None
    corrected_answer: Text | None = None
    reward_candidate: Score | None = None
    provenance: ExperienceProvenance
    consent: TrainingConsent

    @field_validator("alternatives", mode="before")
    @classmethod
    def copy_alternatives(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class TrainingExample(_ImmutableModel):
    """One future supervised-training example with full authorization metadata."""

    example_id: Identifier
    prompt_context: Text
    decision: Text
    alternatives: Annotated[tuple[Text, ...], Field(max_length=16)]
    output: Text
    review: Text | None
    user_feedback: Text | None
    reward_candidate: Score | None
    provenance: ExperienceProvenance
    consent: TrainingConsent


class PreferencePair(_ImmutableModel):
    """One explicitly corrected preferred/rejected pair for future learning."""

    pair_id: Identifier
    prompt_context: Text
    preferred: Text
    rejected: Text
    provenance: ExperienceProvenance
    consent: TrainingConsent


class TrainingDataset(_ImmutableModel):
    """Versioned, bounded dataset produced without triggering training."""

    name: Identifier
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    examples: Annotated[tuple[TrainingExample, ...], Field(max_length=1_000)]
    preference_pairs: Annotated[tuple[PreferencePair, ...], Field(max_length=1_000)]
    excluded_count: Annotated[int, Field(ge=0, le=1_000)]
    exclusion_reasons: Annotated[tuple[DatasetExclusionReason, ...], Field(max_length=8)]
