"""Versioned, non-authorizing collaboration baselines for Agent Genome."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_OBSERVATIONS = 512
_ALGORITHM_VERSION = "genome-collaboration-baseline-v1"


class CollaborationChannel(StrEnum):
    INTERNAL_EVENT = "INTERNAL_EVENT"
    TEAM_SCRATCHPAD = "TEAM_SCRATCHPAD"
    TOOL_MEDIATED = "TOOL_MEDIATED"
    EXTERNAL = "EXTERNAL"


class CollaborationDataClass(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class CollaborationBaselineState(StrEnum):
    COLD_START = "COLD_START"
    ESTABLISHED = "ESTABLISHED"


class _StrictCollaborationModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CollaborationObservation(_StrictCollaborationModel):
    evidence_id: UUID
    project_id: UUID
    task_id: UUID
    agent_id: UUID
    peer_agent_id: UUID | None
    channel: CollaborationChannel
    data_classification: CollaborationDataClass
    delegated: bool
    messages_in_window: Annotated[int, Field(ge=1, le=100_000)]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be UTC-aware")
        return value


class CollaborationBaseline(_StrictCollaborationModel):
    agent_id: UUID
    genome_version_id: UUID
    baseline_version: Annotated[int, Field(ge=1, le=1_000_000)]
    state: CollaborationBaselineState
    normal_peer_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_OBSERVATIONS)]
    normal_channels: Annotated[tuple[CollaborationChannel, ...], Field(max_length=4)]
    normal_data_classes: Annotated[tuple[CollaborationDataClass, ...], Field(max_length=4)]
    minimum_messages_per_window: Annotated[int, Field(ge=1, le=100_000)] | None
    maximum_messages_per_window: Annotated[int, Field(ge=1, le=100_000)] | None
    delegated_interaction_rate: Annotated[
        Decimal, Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)
    ]
    sample_count: Annotated[int, Field(ge=0, le=_MAX_OBSERVATIONS)]
    evidence_ids: Annotated[tuple[UUID, ...], Field(max_length=_MAX_OBSERVATIONS)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    created_at: datetime
    may_grant_communication_authority: Literal[False] = False
    may_mutate_permissions: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be UTC-aware")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        cold = self.state is CollaborationBaselineState.COLD_START
        if cold != (self.sample_count == 0):
            raise ValueError("cold-start state must match an empty sample")
        if self.sample_count != len(self.evidence_ids):
            raise ValueError("sample_count must match evidence_ids")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        if cold != (self.minimum_messages_per_window is None):
            raise ValueError("cold-start frequency bounds must be absent")
        if cold != (self.maximum_messages_per_window is None):
            raise ValueError("cold-start frequency bounds must be absent")
        return self


class CollaborationBaselineBuilder:
    """Build historical patterns without interpreting them as communication permission."""

    def build(
        self,
        *,
        agent_id: UUID,
        genome_version_id: UUID,
        baseline_version: int,
        observations: tuple[CollaborationObservation, ...],
        created_at: datetime,
    ) -> CollaborationBaseline:
        if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
            raise ValueError("observations must be a bounded tuple")
        if any(type(item) is not CollaborationObservation for item in observations):
            raise TypeError("observations must be canonical CollaborationObservation values")
        if any(item.agent_id != agent_id for item in observations):
            raise ValueError("observations must belong to the baseline agent")
        evidence_ids = tuple(item.evidence_id for item in observations)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("observation evidence identifiers must be unique")
        if any(item.observed_at > created_at for item in observations):
            raise ValueError("collaboration observations cannot follow baseline creation")
        count = len(observations)
        return CollaborationBaseline(
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            baseline_version=baseline_version,
            state=(
                CollaborationBaselineState.ESTABLISHED
                if observations
                else CollaborationBaselineState.COLD_START
            ),
            normal_peer_ids=tuple(
                sorted(
                    {item.peer_agent_id for item in observations if item.peer_agent_id is not None},
                    key=str,
                )
            ),
            normal_channels=tuple(sorted({item.channel for item in observations}, key=str)),
            normal_data_classes=tuple(
                sorted({item.data_classification for item in observations}, key=str)
            ),
            minimum_messages_per_window=(
                min(item.messages_in_window for item in observations) if observations else None
            ),
            maximum_messages_per_window=(
                max(item.messages_in_window for item in observations) if observations else None
            ),
            delegated_interaction_rate=(
                (Decimal(sum(item.delegated for item in observations)) / Decimal(count)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                if count
                else Decimal("0.0000")
            ),
            sample_count=count,
            evidence_ids=evidence_ids,
            algorithm_version=_ALGORITHM_VERSION,
            created_at=created_at,
        )
