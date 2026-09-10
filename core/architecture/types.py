"""Immutable contracts for the technology-neutral Phase 26 Architecture Agent."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.intake import IntakeResult


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text255 = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_require_nonblank)]
Text2048 = Annotated[str, Field(min_length=1, max_length=2_048), AfterValidator(_require_nonblank)]
Text8192 = Annotated[str, Field(min_length=1, max_length=8_192), AfterValidator(_require_nonblank)]
UnitScore = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class ArchitectureStatus(StrEnum):
    """Locally derived state of an architecture proposal."""

    PROPOSED = "PROPOSED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class _ImmutableArchitectureModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ArchitectureRequest(_ImmutableArchitectureModel):
    """Validated Phase 25 intake and bounded project context."""

    project_id: Identifier
    intake: IntakeResult
    project_context: Annotated[tuple[Text2048, ...], Field(max_length=32)]

    @field_validator("project_context", mode="before")
    @classmethod
    def copy_context(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class ArchitectureOption(_ImmutableArchitectureModel):
    """One technology-neutral candidate with explicit trade-offs."""

    id: Identifier
    name: Text255
    stack: Annotated[tuple[Text255, ...], Field(min_length=1, max_length=16)]
    benefits: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=16)]
    drawbacks: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=16)]

    @field_validator("stack", "benefits", "drawbacks", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class ADRDraft(_ImmutableArchitectureModel):
    """Non-persisted architecture decision record proposal."""

    selected_option_id: Identifier
    title: Text255
    context: Text8192
    decision: Identifier
    alternatives: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=16)]
    consequences: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=16)]

    @field_validator("alternatives", "consequences", mode="before")
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value


class ArchitectureAnalysis(_ImmutableArchitectureModel):
    """Bounded architecture proposal returned by the provider."""

    architecture: Text8192
    options: Annotated[tuple[ArchitectureOption, ...], Field(min_length=2, max_length=8)]
    selected_option_id: Identifier
    recommendation: Identifier
    recommendation_rationale: Text8192
    confidence: UnitScore
    risks: Annotated[tuple[Text2048, ...], Field(max_length=32)]
    domains: Annotated[tuple[Text255, ...], Field(min_length=1, max_length=32)]
    modules: Annotated[tuple[Text255, ...], Field(min_length=1, max_length=64)]
    proposed_stack: Annotated[tuple[Text255, ...], Field(min_length=1, max_length=16)]
    missing_information: Annotated[tuple[Text2048, ...], Field(max_length=96)]
    adr_draft: ADRDraft

    @field_validator(
        "options",
        "risks",
        "domains",
        "modules",
        "proposed_stack",
        "missing_information",
        mode="before",
    )
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_candidates_and_structure(self) -> Self:
        option_ids = tuple(option.id for option in self.options)
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("architecture option IDs must be unique")
        option_names = tuple(option.name.casefold() for option in self.options)
        if len(option_names) != len(set(option_names)):
            raise ValueError("architecture option names must be unique")
        for values in (self.domains, self.modules, self.proposed_stack):
            normalized = tuple(value.casefold() for value in values)
            if len(normalized) != len(set(normalized)):
                raise ValueError("architecture lists must contain unique values")
        selected = next(
            (option for option in self.options if option.id == self.selected_option_id),
            None,
        )
        if selected is None:
            raise ValueError("selected architecture option must exist")
        if self.adr_draft.selected_option_id != self.selected_option_id:
            raise ValueError("ADR draft must reference the selected architecture option")
        if self.recommendation != self.selected_option_id:
            raise ValueError("recommendation must identify the selected architecture option")
        if self.adr_draft.decision != self.selected_option_id:
            raise ValueError("ADR decision must identify the selected architecture option")
        selected_stack = tuple(value.casefold() for value in selected.stack)
        proposed_stack = tuple(value.casefold() for value in self.proposed_stack)
        if proposed_stack != selected_stack:
            raise ValueError("proposed stack must match the selected architecture option")
        return self


class ArchitectureResult(_ImmutableArchitectureModel):
    """Locally gated architecture proposal safe for later human review."""

    analysis: ArchitectureAnalysis
    status: ArchitectureStatus
    requires_escalation: bool

    @model_validator(mode="after")
    def require_deterministic_escalation(self) -> Self:
        requires_escalation = bool(self.analysis.missing_information)
        expected = (
            ArchitectureStatus.NEEDS_HUMAN if requires_escalation else ArchitectureStatus.PROPOSED
        )
        if self.requires_escalation is not requires_escalation or self.status is not expected:
            raise ValueError("architecture escalation is inconsistent")
        return self


def build_architecture_result(analysis: ArchitectureAnalysis) -> ArchitectureResult:
    """Derive escalation without trusting a provider-supplied readiness decision."""
    requires_escalation = bool(analysis.missing_information)
    return ArchitectureResult(
        analysis=analysis,
        status=(
            ArchitectureStatus.NEEDS_HUMAN if requires_escalation else ArchitectureStatus.PROPOSED
        ),
        requires_escalation=requires_escalation,
    )
