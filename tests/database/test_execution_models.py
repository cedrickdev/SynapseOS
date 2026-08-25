"""ORM contract tests for execution and decision models."""

from __future__ import annotations

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.database.models import AgentRun, Decision, ToolCall


def test_execution_models_expose_required_columns() -> None:
    assert set(AgentRun.__table__.columns.keys()) == {
        "id",
        "agent_id",
        "task_id",
        "status",
        "started_at",
        "finished_at",
        "iteration",
        "confidence",
        "error_message",
        "created_at",
    }
    assert set(Decision.__table__.columns.keys()) == {
        "id",
        "decision",
        "alternatives",
        "justification",
        "confidence",
        "evidence",
        "agent_id",
        "task_id",
        "outcome",
        "final_result",
        "created_at",
        "updated_at",
    }
    assert set(ToolCall.__table__.columns.keys()) == {
        "id",
        "agent_run_id",
        "tool_name",
        "action",
        "input_data",
        "output_data",
        "status",
        "started_at",
        "finished_at",
        "error_message",
        "created_at",
    }


def test_confidence_is_deterministic_numeric() -> None:
    for column in (AgentRun.__table__.c.confidence, Decision.__table__.c.confidence):
        assert isinstance(column.type, Numeric)
        assert column.type.precision == 5
        assert column.type.scale == 4


def test_execution_json_fields_use_postgresql_jsonb() -> None:
    for column in (
        Decision.__table__.c.alternatives,
        Decision.__table__.c.evidence,
        ToolCall.__table__.c.input_data,
        ToolCall.__table__.c.output_data,
    ):
        assert isinstance(column.type, JSONB)


def test_execution_foreign_keys_restrict_historical_deletion() -> None:
    for table in (AgentRun.__table__, Decision.__table__, ToolCall.__table__):
        assert {fk.ondelete for fk in table.foreign_keys} == {"RESTRICT"}
