"""Contract tests for sanitized runtime-step auditing."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from pydantic import ValidationError

from core.runtime import RuntimeAuditOutcome, RuntimeAuditRecord, RuntimeStep


def _record(**changes: object) -> RuntimeAuditRecord:
    values: dict[str, object] = {
        "agent_id": "developer-agent",
        "agent_run_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "correlation_id": uuid.uuid4(),
        "iteration": 1,
        "step": RuntimeStep.PLAN,
        "outcome": RuntimeAuditOutcome.SUCCEEDED,
        "duration_ms": 12,
        "tool_calls": 0,
        "failures": 0,
        "reported_tokens": 42,
    }
    values.update(changes)
    return RuntimeAuditRecord.model_validate(values, strict=True)


def test_runtime_audit_record_is_immutable_and_rejects_unknown_content() -> None:
    record = _record()

    with pytest.raises(ValidationError):
        RuntimeAuditRecord.model_validate(
            {**record.model_dump(), "prompt": "must never be persisted"}, strict=True
        )
    with pytest.raises(ValidationError):
        cast(Any, record).iteration = 2


@pytest.mark.parametrize("field", ["duration_ms", "tool_calls", "failures", "reported_tokens"])
def test_runtime_audit_counters_cannot_be_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        _record(**{field: -1})
