"""Real-PostgreSQL tests for append-only usage records."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.budget.types import UsageKind
from infrastructure.database.append_only import AppendOnlyViolationError
from infrastructure.database.models import Project, UsageRecord
from infrastructure.database.repositories.usage_records import UsageRecordRepository


def test_usage_record_repository_appends_and_reads_usage(db_session: Session) -> None:
    project_id = uuid4()
    project = Project(id=project_id, name="Usage project")
    repository = UsageRecordRepository(db_session)
    db_session.add(project)
    db_session.flush()
    record = repository.add(
        UsageRecord(
            project_id=project_id,
            kind=UsageKind.LLM_REQUEST,
            provider="ollama",
            model="qwen",
            input_tokens=20,
            output_tokens=10,
            duration_ms=42.0,
            tool_calls=0,
        )
    )
    db_session.commit()

    assert repository.get_by_id(record.id) is record
    assert repository.list(project_id=project_id) == [record]
    assert db_session.scalar(select(UsageRecord).where(UsageRecord.id == record.id)) is record


def test_usage_record_update_and_mutable_metadata_are_rejected(db_session: Session) -> None:
    project = Project(name="Immutable usage project")
    record = UsageRecord(project=project, kind=UsageKind.TOOL_CALL, metadata_={"step": "run"})
    db_session.add(record)
    db_session.commit()

    record.provider = "forbidden-update"
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
    db_session.rollback()

    loaded_record = db_session.get(UsageRecord, record.id)
    assert loaded_record is not None
    loaded_record.metadata_["step"] = "forbidden-json-update"
    with pytest.raises(AppendOnlyViolationError):
        db_session.flush()
