"""Deterministic selection of explicitly trusted agent components."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.component_trust import ComponentTrustLevel as ComponentTrustLevel


class _StrictComponentModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustedComponentCandidate(_StrictComponentModel):
    component_id: UUID
    component_type: Annotated[str, Field(min_length=1, max_length=32)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    version: Annotated[str, Field(min_length=1, max_length=128)]
    capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    trust_level: ComponentTrustLevel
    trust_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    governor_allowed: bool
    security_blocked: bool
    trust_manifest_ref: Annotated[str, Field(min_length=1, max_length=512)]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("component evaluation time must be UTC-aware")
        return value

    @field_validator("component_type")
    @classmethod
    def validate_component_type(cls, value: str) -> str:
        allowed = {
            "AGENT_PACKAGE",
            "SKILL",
            "MCP_SERVER",
            "PLAYBOOK",
            "TOOL_PLUGIN",
            "MODEL_ADAPTER",
        }
        if value not in allowed:
            raise ValueError("unsupported component type")
        return value

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("component capabilities must be unique")
        if any(
            not value
            or len(value) > 128
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
            for value in self.capabilities
        ):
            raise ValueError("component capabilities must be bounded and content-safe")
        return self


class TrustedComponentSelectionRequest(_StrictComponentModel):
    required_capabilities: Annotated[tuple[str, ...], Field(min_length=1, max_length=128)]
    candidates: Annotated[tuple[TrustedComponentCandidate, ...], Field(max_length=1_024)]
    selected_at: datetime

    @field_validator("selected_at")
    @classmethod
    def validate_selected_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("selected_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("required capabilities must be unique")
        identifiers = tuple(item.component_id for item in self.candidates)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("component candidates must be unique")
        if any(item.evaluated_at > self.selected_at for item in self.candidates):
            raise ValueError("component evidence cannot occur in the future")
        return self


class TrustedComponentSelection(_StrictComponentModel):
    selected_component_id: UUID | None
    trust_manifest_ref: str | None
    eligible_component_ids: Annotated[tuple[UUID, ...], Field(max_length=1_024)]
    selected_at: datetime
    may_authorize: Literal[False] = False
    may_execute: Literal[False] = False
    may_install: Literal[False] = False


class ManagerTrustedComponentSelector:
    """Choose only approved candidates already admitted by governance."""

    def select(self, request: TrustedComponentSelectionRequest) -> TrustedComponentSelection:
        if type(request) is not TrustedComponentSelectionRequest:
            raise TypeError("request must be a canonical TrustedComponentSelectionRequest")
        required = set(request.required_capabilities)
        eligible = [
            item
            for item in request.candidates
            if item.trust_level is ComponentTrustLevel.APPROVED
            and item.governor_allowed
            and not item.security_blocked
            and required.issubset(item.capabilities)
        ]
        eligible.sort(
            key=lambda item: (
                -item.trust_score,
                len(set(item.capabilities) - required),
                item.component_id.hex,
            )
        )
        selected = eligible[0] if eligible else None
        return TrustedComponentSelection(
            selected_component_id=selected.component_id if selected else None,
            trust_manifest_ref=selected.trust_manifest_ref if selected else None,
            eligible_component_ids=tuple(item.component_id for item in eligible),
            selected_at=request.selected_at,
        )
