"""Strict append-only audit contracts for Phase 19 Git operations."""

from __future__ import annotations

import math
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import AuditResult
from core.git_workflow.types import GitOperation, GitWorkflowContext

type GitAuditDataValue = str | int | float | bool

GIT_AUDIT_DATA_KEYS = frozenset(
    {
        "branch_kind",
        "branch_name",
        "base_branch",
        "commit_sha",
        "selected_path_count",
        "changed_path_count",
        "commit_count",
        "insertions",
        "deletions",
        "status",
        "error_code",
        "output_bytes",
        "truncated",
        "duration_ms",
        "preparation_checksum",
        "merge_decision",
        "reason_codes",
    }
)
_NUMERIC_KEYS = frozenset(
    {
        "selected_path_count",
        "changed_path_count",
        "commit_count",
        "insertions",
        "deletions",
        "output_bytes",
        "duration_ms",
    }
)


class GitAuditStage(StrEnum):
    """Durable lifecycle stage for one attempted Git operation."""

    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GitAuditRecord(BaseModel):
    """One bounded metadata-only Git operation audit record."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    context: GitWorkflowContext
    operation: GitOperation
    stage: GitAuditStage
    result: AuditResult
    data: Annotated[dict[str, GitAuditDataValue], Field(max_length=18)]

    @field_validator("context", mode="before")
    @classmethod
    def require_canonical_context(cls, value: object) -> object:
        if type(value) is not GitWorkflowContext:
            raise ValueError("Git audit context must be canonical")
        return value

    @field_validator("operation", mode="before")
    @classmethod
    def require_canonical_operation(cls, value: object) -> object:
        if type(value) is not GitOperation:
            raise ValueError("Git audit operation must be canonical")
        return value

    @field_validator("stage", mode="before")
    @classmethod
    def require_canonical_stage(cls, value: object) -> object:
        if type(value) is not GitAuditStage:
            raise ValueError("Git audit stage must be canonical")
        return value

    @field_validator("result", mode="before")
    @classmethod
    def require_canonical_result(cls, value: object) -> object:
        if type(value) is not AuditResult:
            raise ValueError("Git audit result must be canonical")
        return value

    @field_validator("data", mode="before")
    @classmethod
    def copy_and_validate_data(cls, value: object) -> object:
        if not isinstance(value, dict) or not set(value).issubset(GIT_AUDIT_DATA_KEYS):
            raise ValueError("Git audit data is invalid")
        return dict(value)

    @field_validator("data")
    @classmethod
    def freeze_data(
        cls,
        value: dict[str, GitAuditDataValue],
    ) -> dict[str, GitAuditDataValue]:
        for key, item in value.items():
            if type(item) not in (str, int, float, bool):
                raise ValueError("Git audit data is invalid")
            if isinstance(item, str) and len(item) > 255:
                raise ValueError("Git audit data is invalid")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Git audit data is invalid")
            if key in _NUMERIC_KEYS and (
                isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0
            ):
                raise ValueError("Git audit data is invalid")
        return MappingProxyType(dict(value))  # type: ignore[return-value]

    @model_validator(mode="after")
    def require_consistent_stage(self) -> Self:
        if self.stage in {GitAuditStage.STARTED, GitAuditStage.COMPLETED}:
            if self.result is not AuditResult.SUCCEEDED:
                raise ValueError("Git audit stage and result are inconsistent")
        elif self.result not in {AuditResult.FAILED, AuditResult.DENIED}:
            raise ValueError("Git audit stage and result are inconsistent")
        return self
