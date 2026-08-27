"""Strict contract tests for managed project workspaces."""

from __future__ import annotations

from math import inf, nan
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.enums import AuditActorType, AuditResult
from core.workspaces import (
    Workspace,
    WorkspaceAuditContext,
    WorkspaceAuditRecord,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceLimits,
    WorkspaceOperation,
    WorkspaceProvenance,
    WorkspaceResourceUsage,
)


def _workspace_root(tmp_path: Path) -> tuple[Path, UUID]:
    project_id = uuid4()
    root = tmp_path / "projects" / str(project_id)
    root.mkdir(parents=True)
    return root.resolve(), project_id


def _audit_context(project_id: UUID) -> WorkspaceAuditContext:
    return WorkspaceAuditContext(
        actor_type=AuditActorType.SYSTEM,
        actor_id="workspace-manager",
        project_id=project_id,
        correlation_id=uuid4(),
    )


def _limits(**changes: object) -> WorkspaceLimits:
    values: dict[str, object] = {
        "git_timeout_seconds": 30.0,
        "git_output_bytes": 65_536,
        "max_entries": 100_000,
        "max_total_bytes": 1_073_741_824,
        "max_depth": 64,
        "max_local_roots": 32,
        "max_remote_hosts": 32,
    }
    values.update(changes)
    return WorkspaceLimits.model_validate(values, strict=True)


def test_workspace_is_frozen_and_canonical(tmp_path: Path) -> None:
    root, project_id = _workspace_root(tmp_path)

    workspace = Workspace(
        project_id=project_id,
        root=root,
        provenance=WorkspaceProvenance.EMPTY,
    )

    assert workspace.root == root
    assert workspace.project_id == project_id
    with pytest.raises(ValidationError):
        workspace.root = tmp_path  # type: ignore[misc]


def test_workspace_rejects_missing_noncanonical_and_untyped_roots(tmp_path: Path) -> None:
    root, project_id = _workspace_root(tmp_path)
    noncanonical = root / ".." / root.name

    for rejected_root in (noncanonical, tmp_path / "missing"):
        with pytest.raises(ValidationError, match="workspace root") as captured:
            Workspace(
                project_id=project_id,
                root=rejected_root,
                provenance=WorkspaceProvenance.EMPTY,
            )
        assert str(tmp_path) not in str(captured.value)

    with pytest.raises(ValidationError):
        Workspace.model_validate(
            {
                "project_id": project_id,
                "root": root,
                "provenance": "EMPTY",
            },
            strict=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("git_timeout_seconds", 0.0),
        ("git_timeout_seconds", inf),
        ("git_timeout_seconds", nan),
        ("git_output_bytes", 1_048_577),
        ("max_entries", 1_000_001),
        ("max_total_bytes", 1_099_511_627_777),
        ("max_depth", 257),
        ("max_local_roots", 257),
        ("max_remote_hosts", 257),
    ],
)
def test_workspace_limits_reject_unbounded_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _limits(**{field: value})


def test_workspace_limits_accept_finite_operational_bounds() -> None:
    limits = _limits()

    assert limits.git_timeout_seconds == 30.0
    assert limits.max_depth == 64


def test_audit_context_requires_exact_actor_and_nonblank_identity() -> None:
    project_id = uuid4()

    context = _audit_context(project_id)

    assert context.actor_type is AuditActorType.SYSTEM
    for values in (
        {**context.model_dump(), "actor_type": "SYSTEM"},
        {**context.model_dump(), "actor_id": "   "},
    ):
        with pytest.raises(ValidationError):
            WorkspaceAuditContext.model_validate(values, strict=True)


def test_audit_record_copies_allowlisted_data_and_requires_matching_project() -> None:
    project_id = uuid4()
    source_data: dict[str, str | int | float | bool] = {
        "provenance": "EMPTY",
        "duration_ms": 4.0,
        "entry_count": 0,
        "total_bytes": 0,
    }
    record = WorkspaceAuditRecord(
        context=_audit_context(project_id),
        project_id=project_id,
        operation=WorkspaceOperation.CREATE,
        result=AuditResult.SUCCEEDED,
        data=source_data,
    )
    source_data["entry_count"] = 99

    assert record.data["entry_count"] == 0
    with pytest.raises(TypeError):
        record.data["entry_count"] = 1

    with pytest.raises(ValidationError):
        WorkspaceAuditRecord(
            context=_audit_context(project_id),
            project_id=uuid4(),
            operation=WorkspaceOperation.CREATE,
            result=AuditResult.FAILED,
            data={"error_code": "PROJECT_UNAVAILABLE"},
        )
    with pytest.raises(ValidationError):
        WorkspaceAuditRecord(
            context=_audit_context(project_id),
            project_id=project_id,
            operation=WorkspaceOperation.CREATE,
            result=AuditResult.FAILED,
            data={"path": "secret-host-path"},
        )


def test_resource_usage_rejects_negative_or_unbounded_counts() -> None:
    usage = WorkspaceResourceUsage(entry_count=3, total_bytes=42, max_depth=2)
    assert usage.entry_count == 3

    for values in (
        {"entry_count": -1, "total_bytes": 0, "max_depth": 0},
        {"entry_count": 0, "total_bytes": -1, "max_depth": 0},
        {"entry_count": 0, "total_bytes": 0, "max_depth": 257},
    ):
        with pytest.raises(ValidationError):
            WorkspaceResourceUsage.model_validate(values, strict=True)


def test_workspace_error_exposes_only_stable_code_and_safe_message() -> None:
    error = WorkspaceError(
        WorkspaceErrorCode.SOURCE_DENIED,
        "Workspace source is not allowed.",
    )

    assert error.code is WorkspaceErrorCode.SOURCE_DENIED
    assert str(error) == "Workspace source is not allowed."
