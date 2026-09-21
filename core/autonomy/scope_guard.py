"""Deterministic task-scope and intent guard for proposed Governor actions."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy.action_evaluation import GovernorActionEvaluationRequest
from core.autonomy.risk import GovernedActionType

_MAX_ACTION_TYPES = len(GovernedActionType)
_MAX_REFERENCES = 64


class GovernorScopeDisposition(StrEnum):
    """Closed scope comparison result without execution authority."""

    WITHIN_SCOPE = "WITHIN_SCOPE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"


class ScopeMismatchReason(StrEnum):
    """Closed deterministic reasons that an action is outside its authorized mission."""

    ACTION_OUT_OF_SCOPE = "ACTION_OUT_OF_SCOPE"
    TOOL_OUT_OF_SCOPE = "TOOL_OUT_OF_SCOPE"
    RESOURCE_OUT_OF_SCOPE = "RESOURCE_OUT_OF_SCOPE"


class _StrictScopeModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class GovernorAuthorizedScope(_StrictScopeModel):
    """Explicit deterministic task scope supplied by trusted backend policy."""

    task_id: UUID
    allowed_action_types: Annotated[
        tuple[GovernedActionType, ...], Field(min_length=1, max_length=_MAX_ACTION_TYPES)
    ]
    allowed_tool_references: Annotated[
        tuple[str, ...], Field(min_length=1, max_length=_MAX_REFERENCES)
    ]
    allowed_resource_prefixes: Annotated[tuple[str, ...], Field(max_length=_MAX_REFERENCES)] = ()
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("allowed_tool_references", "allowed_resource_prefixes")
    @classmethod
    def validate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique bounded opaque references without control characters."""
        if len(set(value)) != len(value):
            raise ValueError("scope references must be unique")
        if any(
            not item
            or len(item) > 512
            or item != item.strip()
            or any(ord(character) < 32 for character in item)
            for item in value
        ):
            raise ValueError("scope references must be bounded, trimmed, and content-safe")
        return value

    @model_validator(mode="after")
    def validate_action_types(self) -> Self:
        if len(set(self.allowed_action_types)) != len(self.allowed_action_types):
            raise ValueError("allowed action types must be unique")
        return self


class GovernorScopeEvaluation(_StrictScopeModel):
    """A scope signal that cannot authorize or execute the proposed action."""

    request: GovernorActionEvaluationRequest
    scope_policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    disposition: GovernorScopeDisposition
    reason_codes: Annotated[tuple[ScopeMismatchReason, ...], Field(max_length=3)]
    resource_reference: Annotated[str, Field(min_length=1, max_length=512)] | None
    requires_permission_check: Literal[True] = True
    may_execute: Literal[False] = False

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        mismatch = bool(self.reason_codes)
        if mismatch != (self.disposition is GovernorScopeDisposition.SCOPE_MISMATCH):
            raise ValueError("scope mismatch disposition must match its reason codes")
        return self


class GovernorScopeIntentGuard:
    """Compare each action to explicit scope; never infer authority from natural language."""

    def evaluate(
        self,
        request: GovernorActionEvaluationRequest,
        *,
        scope: GovernorAuthorizedScope,
        resource_reference: str | None = None,
    ) -> GovernorScopeEvaluation:
        """Return stable mismatch reasons from action, tool, and resource constraints."""
        if type(request) is not GovernorActionEvaluationRequest:
            raise TypeError("request must be a canonical GovernorActionEvaluationRequest")
        if type(scope) is not GovernorAuthorizedScope:
            raise TypeError("scope must be a canonical GovernorAuthorizedScope")
        if request.task_id != scope.task_id:
            raise ValueError("action request and authorized scope must target the same task")
        if resource_reference is not None and (
            not resource_reference
            or len(resource_reference) > 512
            or resource_reference != resource_reference.strip()
            or any(ord(character) < 32 for character in resource_reference)
        ):
            raise ValueError("resource_reference must be bounded, trimmed, and content-safe")

        reasons: list[ScopeMismatchReason] = []
        if request.risk_context.action_type not in scope.allowed_action_types:
            reasons.append(ScopeMismatchReason.ACTION_OUT_OF_SCOPE)
        if request.action_reference not in scope.allowed_tool_references:
            reasons.append(ScopeMismatchReason.TOOL_OUT_OF_SCOPE)
        resource_allowed = (
            resource_reference is None
            and not scope.allowed_resource_prefixes
            or resource_reference is not None
            and any(
                resource_reference.startswith(prefix) for prefix in scope.allowed_resource_prefixes
            )
        )
        if not resource_allowed:
            reasons.append(ScopeMismatchReason.RESOURCE_OUT_OF_SCOPE)

        reason_codes = tuple(reasons)
        return GovernorScopeEvaluation(
            request=request,
            scope_policy_version=scope.policy_version,
            disposition=(
                GovernorScopeDisposition.SCOPE_MISMATCH
                if reason_codes
                else GovernorScopeDisposition.WITHIN_SCOPE
            ),
            reason_codes=reason_codes,
            resource_reference=resource_reference,
        )
