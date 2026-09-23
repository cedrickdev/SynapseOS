"""Fail-closed, non-authorizing Governor communication-policy enforcement."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.genome import CollaborationChannel, CollaborationDataClass
from core.security import SecurityDecision

_IDENTIFIER = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class CommunicationPolicyDisposition(StrEnum):
    """Whether a proposal is denied or may proceed to authoritative permission checks."""

    PROCEED_TO_PERMISSION_CHECK = "PROCEED_TO_PERMISSION_CHECK"
    DENY = "DENY"


class CommunicationPolicyReason(StrEnum):
    """Closed, non-sensitive reasons for fail-closed communication denial."""

    NO_ACTIVE_POLICY = "NO_ACTIVE_POLICY"
    POLICY_NOT_ACTIVE = "POLICY_NOT_ACTIVE"
    PROJECT_OR_TASK_MISMATCH = "PROJECT_OR_TASK_MISMATCH"
    SENDER_NOT_AUTHORIZED = "SENDER_NOT_AUTHORIZED"
    RECIPIENT_NOT_AUTHORIZED = "RECIPIENT_NOT_AUTHORIZED"
    PURPOSE_NOT_AUTHORIZED = "PURPOSE_NOT_AUTHORIZED"
    CHANNEL_NOT_AUTHORIZED = "CHANNEL_NOT_AUTHORIZED"
    DATA_CLASS_NOT_AUTHORIZED = "DATA_CLASS_NOT_AUTHORIZED"
    DELEGATION_NOT_AUTHORIZED = "DELEGATION_NOT_AUTHORIZED"
    SCOPE_NOT_AUTHORIZED = "SCOPE_NOT_AUTHORIZED"
    SECURITY_VETO = "SECURITY_VETO"


class _StrictCommunicationPolicyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CommunicationPolicyGrant(_StrictCommunicationPolicyModel):
    """One explicit bounded communication allowance; never an execution credential."""

    policy_id: UUID
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    project_id: UUID
    task_id: UUID
    sender_agent_id: UUID
    recipient_agent_id: UUID | None
    allowed_purposes: Annotated[tuple[_IDENTIFIER, ...], Field(min_length=1, max_length=32)]
    allowed_channels: Annotated[tuple[CollaborationChannel, ...], Field(min_length=1, max_length=4)]
    allowed_data_classes: Annotated[
        tuple[CollaborationDataClass, ...], Field(min_length=1, max_length=4)
    ]
    delegation_id: UUID
    allowed_scopes: Annotated[tuple[_IDENTIFIER, ...], Field(min_length=1, max_length=32)]
    valid_from: datetime
    expires_at: datetime
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256)]

    @field_validator("valid_from", "expires_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("communication policy timestamps must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_grant(self) -> Self:
        if self.valid_from >= self.expires_at:
            raise ValueError("communication policy expiry must follow its start")
        for values, name in (
            (self.allowed_purposes, "allowed_purposes"),
            (self.allowed_channels, "allowed_channels"),
            (self.allowed_data_classes, "allowed_data_classes"),
            (self.allowed_scopes, "allowed_scopes"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        return self


class CommunicationPolicyRequest(_StrictCommunicationPolicyModel):
    """Metadata-only proposal for one agent-to-agent or external communication."""

    communication_id: UUID
    project_id: UUID
    task_id: UUID
    sender_agent_id: UUID
    recipient_agent_id: UUID | None
    purpose: _IDENTIFIER
    channel: CollaborationChannel
    data_classification: CollaborationDataClass
    delegation_id: UUID
    required_scope: _IDENTIFIER
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("requested_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_recipient(self) -> Self:
        if self.channel is not CollaborationChannel.EXTERNAL and self.recipient_agent_id is None:
            raise ValueError("non-external communication requires a recipient agent")
        return self


class CommunicationPolicyResult(_StrictCommunicationPolicyModel):
    """Restrictive Governor evidence that cannot authorize or send a message."""

    request: CommunicationPolicyRequest
    grant: CommunicationPolicyGrant | None
    disposition: CommunicationPolicyDisposition
    reasons: Annotated[tuple[CommunicationPolicyReason, ...], Field(max_length=11)]
    evaluated_at: datetime
    requires_permission_check: Literal[True] = True
    may_authorize_communication: Literal[False] = False
    may_execute: Literal[False] = False
    may_mutate_permissions: Literal[False] = False

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("communication policy reasons must be unique")
        denied = self.disposition is CommunicationPolicyDisposition.DENY
        if denied != bool(self.reasons):
            raise ValueError("communication policy disposition must match denial reasons")
        if self.request.requested_at > self.evaluated_at:
            raise ValueError("communication request cannot follow policy evaluation")
        return self


class CommunicationPolicyEvaluator:
    """Fail closed before the Permission Engine and preserve every superior veto."""

    def evaluate(
        self,
        request: CommunicationPolicyRequest,
        *,
        grant: CommunicationPolicyGrant | None,
        security_decision: SecurityDecision | None = None,
        evaluated_at: datetime | None = None,
    ) -> CommunicationPolicyResult:
        if type(request) is not CommunicationPolicyRequest:
            raise TypeError("request must be a canonical CommunicationPolicyRequest")
        if grant is not None and type(grant) is not CommunicationPolicyGrant:
            raise TypeError("grant must be a canonical CommunicationPolicyGrant")
        if security_decision is not None and type(security_decision) is not SecurityDecision:
            raise TypeError("security_decision must be canonical")
        evaluation_time = request.requested_at if evaluated_at is None else evaluated_at
        if evaluation_time.tzinfo is None or evaluation_time.utcoffset() != UTC.utcoffset(
            evaluation_time
        ):
            raise ValueError("evaluated_at must be UTC-aware")
        if request.requested_at > evaluation_time:
            raise ValueError("communication request cannot follow policy evaluation")

        reasons: list[CommunicationPolicyReason] = []
        if grant is None:
            reasons.append(CommunicationPolicyReason.NO_ACTIVE_POLICY)
        else:
            checks = (
                (
                    not grant.valid_from <= request.requested_at < grant.expires_at,
                    CommunicationPolicyReason.POLICY_NOT_ACTIVE,
                ),
                (
                    grant.project_id != request.project_id or grant.task_id != request.task_id,
                    CommunicationPolicyReason.PROJECT_OR_TASK_MISMATCH,
                ),
                (
                    grant.sender_agent_id != request.sender_agent_id,
                    CommunicationPolicyReason.SENDER_NOT_AUTHORIZED,
                ),
                (
                    grant.recipient_agent_id != request.recipient_agent_id,
                    CommunicationPolicyReason.RECIPIENT_NOT_AUTHORIZED,
                ),
                (
                    request.purpose not in grant.allowed_purposes,
                    CommunicationPolicyReason.PURPOSE_NOT_AUTHORIZED,
                ),
                (
                    request.channel not in grant.allowed_channels,
                    CommunicationPolicyReason.CHANNEL_NOT_AUTHORIZED,
                ),
                (
                    request.data_classification not in grant.allowed_data_classes,
                    CommunicationPolicyReason.DATA_CLASS_NOT_AUTHORIZED,
                ),
                (
                    grant.delegation_id != request.delegation_id,
                    CommunicationPolicyReason.DELEGATION_NOT_AUTHORIZED,
                ),
                (
                    request.required_scope not in grant.allowed_scopes,
                    CommunicationPolicyReason.SCOPE_NOT_AUTHORIZED,
                ),
            )
            reasons.extend(reason for failed, reason in checks if failed)
        if security_decision is SecurityDecision.BLOCK:
            reasons.append(CommunicationPolicyReason.SECURITY_VETO)

        denial_reasons = tuple(reasons)
        return CommunicationPolicyResult(
            request=request,
            grant=grant,
            disposition=(
                CommunicationPolicyDisposition.DENY
                if denial_reasons
                else CommunicationPolicyDisposition.PROCEED_TO_PERMISSION_CHECK
            ),
            reasons=denial_reasons,
            evaluated_at=evaluation_time,
        )
