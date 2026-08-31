"""End-to-end PostgreSQL enforcement at the tool execution boundary."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditResult, Permission
from core.permissions import PermissionEngine
from core.tools import (
    JsonValue,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolResultStatus,
    ToolRiskLevel,
)
from infrastructure.database.models import AuditEvent, Project
from infrastructure.permissions import (
    SQLAlchemyPermissionAuditRecorder,
    SQLAlchemyPermissionPolicy,
)
from infrastructure.tools.audit import SQLAlchemyToolAuditRecorder
from infrastructure.tools.filesystem import ReadFileTool
from tests.database.permission_fixtures import (
    PermissionScope,
    add_permission,
    create_permission_scope,
)
from tests.tools.fakes import FakeTool


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


def _executor(session: Session, scope: PermissionScope, tool: Tool[Any]) -> ToolExecutor:
    return ToolExecutor(
        ToolRegistry([tool]),
        SQLAlchemyToolAuditRecorder(session),
        PermissionEngine(
            SQLAlchemyPermissionPolicy(session),
            SQLAlchemyPermissionAuditRecorder(session),
            clock=lambda: scope.now,
        ),
    )


def test_persisted_grant_allows_audited_read(db_session: Session, tmp_path: Path) -> None:
    marker = "secret-source-marker-41d2"
    filename = "client-requirements.txt"
    (tmp_path / filename).write_text(marker, encoding="utf-8")
    scope = create_permission_scope(db_session)
    add_permission(
        db_session,
        scope,
        Permission.FILESYSTEM_READ,
        project=scope.project,
    )

    result = asyncio.run(
        _executor(db_session, scope, ReadFileTool()).execute(
            "read_file",
            {"path": filename},
            _context(scope, tmp_path, "read_file"),
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.agent_run_id == scope.run.id))
    )
    events_by_type = {event.event_type: event for event in events}
    assert set(events_by_type) == {"PERMISSION_EVALUATED", "TOOL_EXECUTION"}
    assert events_by_type["PERMISSION_EVALUATED"].data["decision"] == "ALLOW"
    assert events_by_type["TOOL_EXECUTION"].result is AuditResult.SUCCEEDED
    persisted = repr([(event.data, event.resource_id) for event in events])
    assert marker not in persisted
    assert filename not in persisted
    assert str(tmp_path) not in persisted


@pytest.mark.parametrize("grant_state", ["missing", "expired", "revoked", "cross-project"])
def test_inactive_or_out_of_scope_grants_never_execute(
    db_session: Session,
    tmp_path: Path,
    grant_state: str,
) -> None:
    scope = create_permission_scope(db_session)
    if grant_state == "expired":
        add_permission(
            db_session,
            scope,
            Permission.FILESYSTEM_READ,
            expires_at=scope.now,
        )
    elif grant_state == "revoked":
        add_permission(
            db_session,
            scope,
            Permission.FILESYSTEM_READ,
            revoked_at=scope.now,
        )
    elif grant_state == "cross-project":
        other_project = Project(name="Unrelated project")
        db_session.add(other_project)
        db_session.flush()
        add_permission(
            db_session,
            scope,
            Permission.FILESYSTEM_READ,
            project=other_project,
        )

    result = asyncio.run(
        _executor(db_session, scope, FakeTool()).execute(
            "fake_read",
            {"path": "README.md"},
            _context(scope, tmp_path, "fake_read"),
        )
    )

    assert result.status is ToolResultStatus.DENIED
    assert result.error_code is ToolErrorCode.PERMISSION_DENIED
    assert FakeTool.calls == 0


class _NoInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _ApprovalTool(Tool[_NoInput]):
    name = "approval_tool"
    description = "Require a permission that cannot execute without approval."
    input_type = _NoInput
    risk_level = ToolRiskLevel.CRITICAL
    timeout_seconds = 1.0

    def __init__(self, permission: Permission) -> None:
        self.required_permissions = frozenset({permission})
        self.calls = 0

    async def execute(
        self,
        arguments: _NoInput,
        context: ToolExecutionContext,
    ) -> Mapping[str, JsonValue]:
        del arguments, context
        self.calls += 1
        return {}


@pytest.mark.parametrize(
    ("permission", "autonomy_level"),
    [
        (Permission.TESTS_EXECUTE, 0),
        (Permission.DEPLOYMENT_PRODUCTION, 5),
    ],
)
def test_approval_decisions_never_execute(
    db_session: Session,
    tmp_path: Path,
    permission: Permission,
    autonomy_level: int,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=autonomy_level)
    add_permission(db_session, scope, permission, project=scope.project)
    tool = _ApprovalTool(permission)

    result = asyncio.run(
        _executor(db_session, scope, tool).execute(
            tool.name,
            {},
            _context(scope, tmp_path, tool.name),
        )
    )

    assert result.status is ToolResultStatus.DENIED
    assert result.error_code is ToolErrorCode.APPROVAL_REQUIRED
    assert tool.calls == 0
