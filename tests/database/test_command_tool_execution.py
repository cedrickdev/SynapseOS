"""Real-PostgreSQL acceptance tests for secure command profile execution."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.commands import CommandLimits
from core.enums import AuditResult, Permission
from core.permissions import PermissionEngine
from core.tools import ToolErrorCode, ToolExecutionContext, ToolExecutor, ToolRegistry
from core.workspaces import WorkspaceLimits
from infrastructure.commands import LocalCommandPolicy, LocalCommandRunner
from infrastructure.database.models import AuditEvent, ToolCall
from infrastructure.permissions import (
    SQLAlchemyPermissionAuditRecorder,
    SQLAlchemyPermissionPolicy,
)
from infrastructure.tools import RunCommandProfileTool
from infrastructure.tools.audit import SQLAlchemyToolAuditRecorder
from infrastructure.workspaces import ManagedWorkspaceFilesystem
from tests.database.permission_fixtures import (
    PermissionScope,
    add_permission,
    create_permission_scope,
)


def _command_tool(
    tmp_path: Path,
    scope: PermissionScope,
) -> tuple[RunCommandProfileTool, Path]:
    filesystem = ManagedWorkspaceFilesystem(
        tmp_path / scope.project.id.hex,
        WorkspaceLimits(
            git_timeout_seconds=5.0,
            git_output_bytes=4_096,
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
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n",
        encoding="utf-8",
    )
    limits = CommandLimits(
        timeout_seconds=5.0,
        stdout_max_bytes=16_384,
        stderr_max_bytes=8_192,
        marker_max_bytes=4_096,
        read_chunk_bytes=1_024,
        termination_grace_seconds=0.5,
    )
    return (
        RunCommandProfileTool(
            LocalCommandPolicy(filesystem, limits),
            LocalCommandRunner(),
        ),
        root,
    )


def _context(scope: PermissionScope, root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=root,
        agent_id=scope.agent.slug,
        agent_run_id=scope.run.id,
        project_id=scope.project.id,
        task_id=scope.task.id,
        declared_tool_ids={"run_command_profile"},
        correlation_id=uuid.uuid4(),
    )


def _executor(
    session: Session, scope: PermissionScope, tool: RunCommandProfileTool
) -> ToolExecutor:
    return ToolExecutor(
        ToolRegistry([tool]),
        SQLAlchemyToolAuditRecorder(session),
        PermissionEngine(
            SQLAlchemyPermissionPolicy(session),
            SQLAlchemyPermissionAuditRecorder(session),
            clock=lambda: scope.now,
        ),
    )


def test_persisted_shell_grant_runs_profile_and_keeps_raw_output_out_of_audit(
    db_session: Session,
    tmp_path: Path,
) -> None:
    marker = "secret-command-output-marker-84f1"
    scope = create_permission_scope(db_session, autonomy_level=3)
    add_permission(db_session, scope, Permission.SHELL_EXECUTE, project=scope.project)
    tool, root = _command_tool(tmp_path, scope)
    (root / "test_failure.py").write_text(
        f"def test_failure():\n    assert False, {marker!r}\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        _executor(db_session, scope, tool).execute(
            "run_command_profile",
            {"profile_id": "pytest"},
            _context(scope, root),
        )
    )

    assert result.error_code is None
    assert result.output["exit_code"] != 0
    assert result.output["terminal_status"] == "FAILED"
    immediate_output = f"{result.output['stdout']}\n{result.output['stderr']}"
    assert marker in immediate_output
    call = db_session.get(ToolCall, result.tool_call_id)
    assert call is not None
    events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.agent_run_id == scope.run.id))
    )
    execution = next(event for event in events if event.event_type == "TOOL_EXECUTION")
    assert execution.result is AuditResult.SUCCEEDED
    persisted = repr(
        (
            call.input_data,
            call.output_data,
            call.error_message,
            [event.data for event in events],
        )
    )
    assert marker not in persisted
    assert "test_failure.py" not in persisted
    assert str(root) not in persisted
    assert "PYTHONPATH" not in persisted


def test_shell_permission_requires_autonomy_three_before_process_execution(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=2)
    add_permission(db_session, scope, Permission.SHELL_EXECUTE, project=scope.project)
    tool, root = _command_tool(tmp_path, scope)
    side_effect = root / "must-not-be-created"
    (root / "conftest.py").write_text(
        f"from pathlib import Path\nPath({str(side_effect)!r}).touch()\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        _executor(db_session, scope, tool).execute(
            "run_command_profile",
            {"profile_id": "pytest"},
            _context(scope, root),
        )
    )

    assert result.error_code is ToolErrorCode.APPROVAL_REQUIRED
    assert not side_effect.exists()
    events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.agent_run_id == scope.run.id))
    )
    execution = next(event for event in events if event.event_type == "TOOL_EXECUTION")
    assert execution.result is AuditResult.DENIED


def test_missing_or_cross_project_shell_grant_never_executes(
    db_session: Session,
    tmp_path: Path,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=3)
    other_scope = create_permission_scope(db_session, autonomy_level=3)
    add_permission(db_session, scope, Permission.SHELL_EXECUTE, project=other_scope.project)
    tool, root = _command_tool(tmp_path, scope)

    result = asyncio.run(
        _executor(db_session, scope, tool).execute(
            "run_command_profile",
            {"profile_id": "pytest"},
            _context(scope, root),
        )
    )

    assert result.error_code is ToolErrorCode.PERMISSION_DENIED
