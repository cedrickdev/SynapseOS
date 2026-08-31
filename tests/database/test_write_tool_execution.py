"""Real-PostgreSQL acceptance tests for transactional write tool execution."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditResult, Permission
from core.permissions import PermissionEngine
from core.tools import (
    ToolAuditError,
    ToolErrorCode,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)
from core.workspaces import WorkspaceLimits
from infrastructure.database.models import AuditEvent, ToolCall
from infrastructure.permissions import (
    SQLAlchemyPermissionAuditRecorder,
    SQLAlchemyPermissionPolicy,
)
from infrastructure.tools import LocalTextMutator, MutationLimits, WriteFileTool
from infrastructure.tools.audit import SQLAlchemyToolAuditRecorder
from infrastructure.tools.write import DeleteFileTool
from infrastructure.workspaces import ManagedWorkspaceFilesystem
from tests.database.permission_fixtures import (
    PermissionScope,
    add_permission,
    create_permission_scope,
)


def _managed(
    tmp_path: Path,
    scope: PermissionScope,
) -> tuple[LocalTextMutator, Path]:
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / scope.project.id.hex,
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=1_024,
            max_entries=1_000,
            max_total_bytes=10_000_000,
            max_depth=16,
            max_local_roots=8,
            max_remote_hosts=8,
        ),
    )
    root = filesystem.promote(
        scope.project.id,
        filesystem.create_staging(scope.project.id),
    )
    mutator = LocalTextMutator(
        filesystem,
        MutationLimits(
            max_input_bytes=4_096,
            max_existing_bytes=4_096,
            max_patch_operations=8,
            max_patch_text_bytes=1_024,
            max_diff_bytes=2_048,
        ),
    )
    return mutator, root


def _context(scope: PermissionScope, root: Path, tool_name: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=root,
        agent_id=scope.agent.slug,
        agent_run_id=scope.run.id,
        project_id=scope.project.id,
        task_id=scope.task.id,
        declared_tool_ids={tool_name},
        correlation_id=uuid.uuid4(),
    )


def _executor(
    session: Session,
    scope: PermissionScope,
    tool: WriteFileTool | DeleteFileTool,
    recorder: SQLAlchemyToolAuditRecorder | None = None,
) -> ToolExecutor:
    return ToolExecutor(
        ToolRegistry([tool]),
        recorder or SQLAlchemyToolAuditRecorder(session),
        PermissionEngine(
            SQLAlchemyPermissionPolicy(session),
            SQLAlchemyPermissionAuditRecorder(session),
            clock=lambda: scope.now,
        ),
    )


def test_persisted_write_grant_mutates_and_appends_sanitized_audits(
    db_session: Session,
    tmp_path: Path,
) -> None:
    marker = "secret-write-content-marker-72a9"
    scope = create_permission_scope(db_session, autonomy_level=1)
    add_permission(db_session, scope, Permission.FILESYSTEM_WRITE, project=scope.project)
    mutator, root = _managed(tmp_path, scope)
    target = root / "module.py"
    target.write_text("before\n", encoding="utf-8")

    result = asyncio.run(
        _executor(db_session, scope, WriteFileTool(mutator)).execute(
            "write_file",
            {"path": "module.py", "content": f"{marker}\n"},
            _context(scope, root, "write_file"),
        )
    )

    assert result.error_code is None
    assert target.read_text(encoding="utf-8") == f"{marker}\n"
    call = db_session.get(ToolCall, result.tool_call_id)
    assert call is not None
    events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.agent_run_id == scope.run.id))
    )
    assert {event.event_type for event in events} == {"PERMISSION_EVALUATED", "TOOL_EXECUTION"}
    assert (
        next(event for event in events if event.event_type == "TOOL_EXECUTION").result
        is AuditResult.SUCCEEDED
    )
    persisted = repr(
        (call.input_data, call.output_data, call.error_message, [event.data for event in events])
    )
    assert marker not in persisted
    assert "module.py" not in persisted
    assert str(root) not in persisted


def test_high_risk_delete_requires_autonomy_two_before_mutation(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=1)
    add_permission(db_session, scope, Permission.FILESYSTEM_WRITE, project=scope.project)
    mutator, root = _managed(tmp_path, scope)
    target = root / "protected.py"
    target.write_text("protected\n", encoding="utf-8")

    result = asyncio.run(
        _executor(db_session, scope, DeleteFileTool(mutator)).execute(
            "delete_file",
            {"path": "protected.py"},
            _context(scope, root, "delete_file"),
        )
    )

    assert result.error_code is ToolErrorCode.APPROVAL_REQUIRED
    assert target.read_text(encoding="utf-8") == "protected\n"


def test_terminal_audit_failure_restores_original_file(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=1)
    add_permission(db_session, scope, Permission.FILESYSTEM_WRITE, project=scope.project)
    mutator, root = _managed(tmp_path, scope)
    target = root / "module.py"
    target.write_text("original\n", encoding="utf-8")
    recorder = SQLAlchemyToolAuditRecorder(db_session)

    with (
        patch.object(recorder, "finish", side_effect=RuntimeError("secret-audit-failure")),
        pytest.raises(ToolAuditError) as captured,
    ):
        asyncio.run(
            _executor(db_session, scope, WriteFileTool(mutator), recorder).execute(
                "write_file",
                {"path": "module.py", "content": "changed\n"},
                _context(scope, root, "write_file"),
            )
        )

    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(root.rglob(".synapseos-write-*")) == []
    assert "secret-audit-failure" not in str(captured.value)
