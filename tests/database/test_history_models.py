"""ORM contract tests for append-only history models."""

from __future__ import annotations

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.database.models import AgentScore, AuditEvent


def test_agent_score_exposes_approved_event_fields() -> None:
    assert set(AgentScore.__table__.columns.keys()) == {
        "id",
        "agent_id",
        "project_id",
        "task_id",
        "score_type",
        "value",
        "justification",
        "source_type",
        "source_id",
        "metadata",
        "created_at",
    }
    assert isinstance(AgentScore.__table__.c.value.type, Numeric)
    assert AgentScore.__table__.c.value.type.precision == 5
    assert AgentScore.__table__.c.value.type.scale == 4
    assert isinstance(AgentScore.__table__.c.metadata.type, JSONB)


def test_audit_event_exposes_approved_trace_fields() -> None:
    assert set(AuditEvent.__table__.columns.keys()) == {
        "id",
        "actor_type",
        "actor_id",
        "project_id",
        "task_id",
        "agent_run_id",
        "event_type",
        "action",
        "resource_type",
        "resource_id",
        "result",
        "data",
        "correlation_id",
        "corrects_event_id",
        "created_at",
    }
    assert isinstance(AuditEvent.__table__.c.data.type, JSONB)
    assert AuditEvent.__table__.c.actor_id.foreign_keys == set()


def test_history_foreign_keys_restrict_deletion() -> None:
    for table in (AgentScore.__table__, AuditEvent.__table__):
        assert {fk.ondelete for fk in table.foreign_keys} == {"RESTRICT"}
