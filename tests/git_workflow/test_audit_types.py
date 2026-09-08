"""Strict metadata-only Git audit contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.enums import AuditResult
from core.git_workflow import GitAuditRecord, GitAuditStage, GitOperation
from tests.git_workflow.factories import git_context


def test_git_audit_data_is_copied_frozen_and_allowlisted(tmp_path: Path) -> None:
    mutable = {
        "branch_name": "feature/task-safe",
        "selected_path_count": 2,
        "truncated": False,
    }
    record = GitAuditRecord(
        context=git_context(tmp_path),
        operation=GitOperation.COMMIT_CHANGES,
        stage=GitAuditStage.COMPLETED,
        result=AuditResult.SUCCEEDED,
        data=mutable,
    )
    mutable["branch_name"] = "forged"

    assert record.data["branch_name"] == "feature/task-safe"
    with pytest.raises(TypeError):
        record.data["branch_name"] = "forged"


@pytest.mark.parametrize(
    "data",
    (
        {"diff": "secret patch"},
        {"path": "private/file.py"},
        {"error": "raw database error"},
        {"branch_name": {"nested": "value"}},
        {"duration_ms": float("inf")},
    ),
)
def test_git_audit_rejects_sensitive_or_unbounded_metadata(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GitAuditRecord(
            context=git_context(Path.cwd()),
            operation=GitOperation.GET_STATUS,
            stage=GitAuditStage.FAILED,
            result=AuditResult.FAILED,
            data=data,
        )


def test_git_audit_requires_consistent_stage_and_result(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        GitAuditRecord(
            context=git_context(tmp_path),
            operation=GitOperation.GET_DIFF,
            stage=GitAuditStage.COMPLETED,
            result=AuditResult.FAILED,
            data={},
        )
