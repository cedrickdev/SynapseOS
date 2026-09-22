"""Non-authorizing Governor validation of delegated action authority."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.autonomy.action_evaluation import GovernorActionEvaluationResult
from core.trust import DelegationIntegrityDisposition, DelegationIntegrityResult


class DelegatedAuthorityDisposition(StrEnum):
    PROCEED_TO_PERMISSION_CHECK = "PROCEED_TO_PERMISSION_CHECK"
    DENY = "DENY"


class DelegatedAuthorityReason(StrEnum):
    DELEGATION_INTEGRITY_VIOLATION = "DELEGATION_INTEGRITY_VIOLATION"
    SCOPE_NOT_DELEGATED = "SCOPE_NOT_DELEGATED"
    CAPABILITY_NOT_DELEGATED = "CAPABILITY_NOT_DELEGATED"


class _StrictDelegatedAuthorityModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class DelegatedAuthorityRequest(_StrictDelegatedAuthorityModel):
    project_id: UUID
    action_evaluation: GovernorActionEvaluationResult
    delegation_integrity: DelegationIntegrityResult
    required_scope: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    required_capability: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        action = self.action_evaluation.request
        chain = self.delegation_integrity.chain
        leaf = chain[-1]
        if leaf.project_id != self.project_id or leaf.task_id != action.task_id:
            raise ValueError("delegation must match the action project and task")
        if leaf.delegate_agent_id != action.agent_id:
            raise ValueError("delegation leaf must identify the acting agent")
        if self.delegation_integrity.evaluated_at > self.evaluated_at:
            raise ValueError("delegation integrity cannot follow authority validation")
        if action.evaluated_at > self.evaluated_at:
            raise ValueError("action evaluation cannot follow authority validation")
        return self


class DelegatedAuthorityResult(_StrictDelegatedAuthorityModel):
    request: DelegatedAuthorityRequest
    disposition: DelegatedAuthorityDisposition
    reasons: Annotated[tuple[DelegatedAuthorityReason, ...], Field(max_length=3)]
    requires_permission_check: Literal[True] = True
    may_execute: Literal[False] = False
    may_mutate_permissions: Literal[False] = False


class GovernorDelegatedAuthorityValidator:
    """Fail closed before the authoritative Permission Engine check."""

    def validate(self, request: DelegatedAuthorityRequest) -> DelegatedAuthorityResult:
        if type(request) is not DelegatedAuthorityRequest:
            raise TypeError("request must be a canonical DelegatedAuthorityRequest")
        leaf = request.delegation_integrity.chain[-1]
        reasons = tuple(
            reason
            for condition, reason in (
                (
                    request.delegation_integrity.disposition
                    is DelegationIntegrityDisposition.INTEGRITY_VIOLATION,
                    DelegatedAuthorityReason.DELEGATION_INTEGRITY_VIOLATION,
                ),
                (
                    request.required_scope not in leaf.allowed_scopes,
                    DelegatedAuthorityReason.SCOPE_NOT_DELEGATED,
                ),
                (
                    request.required_capability not in leaf.allowed_capabilities,
                    DelegatedAuthorityReason.CAPABILITY_NOT_DELEGATED,
                ),
            )
            if condition
        )
        return DelegatedAuthorityResult(
            request=request,
            disposition=(
                DelegatedAuthorityDisposition.DENY
                if reasons
                else DelegatedAuthorityDisposition.PROCEED_TO_PERMISSION_CHECK
            ),
            reasons=reasons,
        )
