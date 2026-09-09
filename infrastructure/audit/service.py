"""Validated append-only audit recording and bounded reconstruction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult
from infrastructure.database.models import AuditEvent
from infrastructure.database.repositories import AuditEventRepository

AuditText = Annotated[str, Field(min_length=1, max_length=255)]
_SENSITIVE_KEYS = frozenset(
    {"api_key", "authorization", "content", "password", "prompt", "response", "secret", "token"}
)


class AuditRecord(BaseModel):
    """Complete bounded input for one standard audit event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_type: AuditActorType
    actor_id: AuditText
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    event_type: AuditText
    action: AuditText
    resource_type: AuditText | None = None
    resource_id: AuditText | None = None
    result: AuditResult
    correlation_id: uuid.UUID | None = None
    metadata: Annotated[dict[str, object], Field(max_length=32)] = Field(default_factory=dict)

    @field_validator("actor_id", "event_type", "action", "resource_type", "resource_id")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("audit text must not be blank")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, object]) -> dict[str, object]:
        for key, item in value.items():
            if key.lower() in _SENSITIVE_KEYS:
                raise ValueError("sensitive audit metadata key is forbidden")
            if len(key) > 64 or not isinstance(item, (str, int, float, bool, type(None))):
                raise ValueError("audit metadata must be shallow and bounded")
            if isinstance(item, str) and len(item) > 1024:
                raise ValueError("audit metadata value is too long")
        return dict(value)


class AuditLogService:
    """Standard API exposing append and read operations only."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = AuditEventRepository(session)

    def append(self, record: AuditRecord) -> AuditEvent:
        event = self._repository.add(
            AuditEvent(
                actor_type=record.actor_type,
                actor_id=record.actor_id,
                project_id=record.project_id,
                task_id=record.task_id,
                agent_run_id=record.agent_run_id,
                event_type=record.event_type,
                action=record.action,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                result=record.result,
                data=dict(record.metadata),
                correlation_id=record.correlation_id,
                created_at=datetime.now(UTC),
            )
        )
        self._session.flush()
        return event

    def get(self, event_id: uuid.UUID) -> AuditEvent | None:
        return self._repository.get_by_id(event_id)

    def search(
        self,
        *,
        actor_type: AuditActorType | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        result: AuditResult | None = None,
        correlation_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        return self._repository.list(
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            correlation_id=correlation_id,
            limit=limit,
            offset=offset,
        )

    def reconstruct(self, correlation_id: uuid.UUID, *, limit: int = 1000) -> list[AuditEvent]:
        events = self._repository.list(correlation_id=correlation_id, limit=limit)
        return list(reversed(events))
