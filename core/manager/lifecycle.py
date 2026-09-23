"""Bounded lifecycle decisions for company-owned agents."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentLifecycleState(StrEnum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRING = "RETIRING"
    RETIRED = "RETIRED"


class LifecycleDisposition(StrEnum):
    ALLOW = "ALLOW"
    DENY_INVALID_TRANSITION = "DENY_INVALID_TRANSITION"
    DENY_SECURITY_BLOCK = "DENY_SECURITY_BLOCK"


class _StrictLifecycleModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class AgentLifecycleRequest(_StrictLifecycleModel):
    agent_id: UUID
    current_state: AgentLifecycleState
    target_state: AgentLifecycleState
    active_credential_lease_ids: Annotated[tuple[UUID, ...], Field(max_length=256)] = ()
    open_session_ids: Annotated[tuple[UUID, ...], Field(max_length=256)] = ()
    security_blocked: bool = False
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_identifiers(self) -> Self:
        for values in (self.active_credential_lease_ids, self.open_session_ids):
            if len(values) != len(set(values)):
                raise ValueError("lifecycle resource identifiers must be unique")
        return self


class AgentLifecycleDecision(_StrictLifecycleModel):
    agent_id: UUID
    previous_state: AgentLifecycleState
    target_state: AgentLifecycleState
    disposition: LifecycleDisposition
    revoke_credential_lease_ids: Annotated[tuple[UUID, ...], Field(max_length=256)]
    close_session_ids: Annotated[tuple[UUID, ...], Field(max_length=256)]
    evaluated_at: datetime
    may_mutate: Literal[False] = False
    may_revoke: Literal[False] = False
    may_close_sessions: Literal[False] = False


class AgentLifecycleManager:
    """Validate lifecycle transitions and describe required cleanup only."""

    _TRANSITIONS = frozenset(
        {
            (AgentLifecycleState.PROVISIONED, AgentLifecycleState.ACTIVE),
            (AgentLifecycleState.ACTIVE, AgentLifecycleState.PAUSED),
            (AgentLifecycleState.PAUSED, AgentLifecycleState.ACTIVE),
            (AgentLifecycleState.ACTIVE, AgentLifecycleState.RETIRING),
            (AgentLifecycleState.PAUSED, AgentLifecycleState.RETIRING),
            (AgentLifecycleState.RETIRING, AgentLifecycleState.RETIRED),
        }
    )
    _REVOKE_STATES = frozenset(
        {
            AgentLifecycleState.PAUSED,
            AgentLifecycleState.RETIRING,
            AgentLifecycleState.RETIRED,
        }
    )

    def evaluate(self, request: AgentLifecycleRequest) -> AgentLifecycleDecision:
        if type(request) is not AgentLifecycleRequest:
            raise TypeError("request must be a canonical AgentLifecycleRequest")
        if (request.current_state, request.target_state) not in self._TRANSITIONS:
            return self._denied(request, LifecycleDisposition.DENY_INVALID_TRANSITION)
        if request.security_blocked and request.target_state is AgentLifecycleState.ACTIVE:
            return self._denied(request, LifecycleDisposition.DENY_SECURITY_BLOCK)

        revoke = (
            tuple(sorted(request.active_credential_lease_ids, key=lambda item: item.hex))
            if request.target_state in self._REVOKE_STATES
            else ()
        )
        close_sessions = (
            tuple(sorted(request.open_session_ids, key=lambda item: item.hex))
            if request.target_state is AgentLifecycleState.RETIRED
            else ()
        )
        return AgentLifecycleDecision(
            agent_id=request.agent_id,
            previous_state=request.current_state,
            target_state=request.target_state,
            disposition=LifecycleDisposition.ALLOW,
            revoke_credential_lease_ids=revoke,
            close_session_ids=close_sessions,
            evaluated_at=request.evaluated_at,
        )

    @staticmethod
    def _denied(
        request: AgentLifecycleRequest,
        disposition: LifecycleDisposition,
    ) -> AgentLifecycleDecision:
        return AgentLifecycleDecision(
            agent_id=request.agent_id,
            previous_state=request.current_state,
            target_state=request.current_state,
            disposition=disposition,
            revoke_credential_lease_ids=(),
            close_session_ids=(),
            evaluated_at=request.evaluated_at,
        )
