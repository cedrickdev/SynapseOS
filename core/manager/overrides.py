"""Immutable human override records for Manager recommendations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.manager.contracts import ManagerDecision


class ManagerHumanOverride(BaseModel):
    """An auditable human replacement of a non-executing Manager recommendation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    id: UUID
    original_recommendation: ManagerDecision
    replacement_recommendation: ManagerDecision
    human_actor_id: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
    ]
    justification: Annotated[str, Field(min_length=1, max_length=1_024)]
    created_at: datetime

    @field_validator("justification")
    @classmethod
    def validate_justification(cls, value: str) -> str:
        """Require a bounded substantive audit justification."""
        if not value.strip():
            raise ValueError("justification must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """Require UTC provenance for the human override."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_replacement_scope(self) -> ManagerHumanOverride:
        """Keep an override bound to the same project and task as its source."""
        original = self.original_recommendation
        replacement = self.replacement_recommendation
        if original.project_id != replacement.project_id or original.task_id != replacement.task_id:
            raise ValueError("replacement recommendation must target the same project and task")
        if original == replacement:
            raise ValueError("replacement recommendation must differ from the original")
        return self
