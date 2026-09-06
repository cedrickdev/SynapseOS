"""PostgreSQL integration tests for Phase 18 Security workflow preflight."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from inspect import signature
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.commands import CommandTerminalStatus
from core.enums import AgentSeniority, AgentStatus, Permission, TaskStatus
from core.qa import QADecision
from core.workflows import (
    SecurityWorkflowError,
    SecurityWorkflowErrorCode,
    SecurityWorkflowRequest,
    validate_security_workflow_request,
)
from infrastructure.database.models import AuditEvent, Task
from tests.security.factories import security_request
from tests.workflows.security_factories import persisted_security_workflow_request

pytest_plugins = ("tests.database.conftest",)


class RecordingForbiddenSession:
    """Record any persistence access made before request canonicalization."""

    def __init__(self) -> None:
        self.accesses: list[str] = []

    def scalar(self, *_args: object, **_kwargs: object) -> None:
        self.accesses.append("scalar")
        raise AssertionError("database access must follow canonicalization")


@contextmanager
def guard_session_lifecycle(session: Session):  # type: ignore[no-untyped-def]
    """Fail immediately if public preflight commits or closes its caller-owned session."""
    with (
        patch.object(
            session,
            "commit",
            side_effect=AssertionError("preflight must not commit"),
        ) as commit,
        patch.object(
            session,
            "close",
            side_effect=AssertionError("preflight must not close"),
        ) as close,
    ):
        yield
    commit.assert_not_called()
    close.assert_not_called()


def assert_rejected_without_side_effects(
    session: Session,
    task: Task,
    request: SecurityWorkflowRequest,
    expected_code: SecurityWorkflowErrorCode,
) -> None:
    """Ensure persistent preflight never transitions, audits, commits, or closes."""
    original_status = task.status
    original_assignment = task.assigned_agent_id
    audit_count = session.scalar(select(func.count()).select_from(AuditEvent))

    with guard_session_lifecycle(session):
        with pytest.raises(SecurityWorkflowError) as raised:
            validate_security_workflow_request(session, request)

        assert raised.value.code is expected_code
        assert task.status is original_status
        assert task.assigned_agent_id == original_assignment
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_count
    assert session.in_transaction()


def test_security_preflight_public_api_has_no_collaborator_parameter() -> None:
    """Keep collaborator execution structurally outside the public validation boundary."""
    assert tuple(signature(validate_security_workflow_request).parameters) == (
        "session",
        "request",
    )


@pytest.mark.parametrize("case", ["profile-name", "context-agent", "source-content"])
def test_security_preflight_canonicalizes_invalid_nested_scalars_before_database_access(
    tmp_path: Path,
    case: str,
) -> None:
    """Reject malformed nested scalars before persistent state can be trusted."""
    nested = security_request(tmp_path)
    if case == "profile-name":
        profile = nested.profile.model_copy(update={"name": 7})
        nested = nested.model_copy(update={"profile": profile})
    elif case == "context-agent":
        context = nested.execution_context.model_copy(update={"agent_id": 7})
        nested = nested.model_copy(update={"execution_context": context})
    else:
        source = nested.affected_files[0].model_copy(update={"content": b"forged"})
        nested = nested.model_copy(update={"affected_files": (source,)})
    request = SecurityWorkflowRequest.model_construct(
        task_id=nested.task_id,
        developer_agent_id=uuid4(),
        reviewer_agent_id=uuid4(),
        qa_agent_id=uuid4(),
        security_agent_id=uuid4(),
        security_request=nested,
        correlation_id=nested.correlation_id,
    )
    session = RecordingForbiddenSession()

    with pytest.raises(SecurityWorkflowError) as raised:
        validate_security_workflow_request(session, request)  # type: ignore[arg-type]

    assert raised.value.code is SecurityWorkflowErrorCode.INVALID_INPUT
    assert session.accesses == []


def test_security_preflight_rejects_forged_non_uuid_scope_before_persistence(
    tmp_path: Path,
) -> None:
    """Require exact UUID values before any caller-owned session is accessed."""
    nested = security_request(tmp_path).model_copy(
        update={"task_id": "task", "correlation_id": "correlation"}
    )
    forged_values: Any = {
        "task_id": "task",
        "developer_agent_id": "developer",
        "reviewer_agent_id": "reviewer",
        "qa_agent_id": "qa",
        "security_agent_id": "security",
        "security_request": nested,
        "correlation_id": "correlation",
    }
    request = SecurityWorkflowRequest.model_construct(**forged_values)

    with pytest.raises(SecurityWorkflowError) as raised:
        validate_security_workflow_request(None, request)  # type: ignore[arg-type]

    assert raised.value.code is SecurityWorkflowErrorCode.INVALID_INPUT


def test_security_preflight_returns_canonical_persistent_scope(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Return exact locked persistent identities and detached nested workflow values."""
    task, developer, reviewer, qa, security, request = persisted_security_workflow_request(
        db_session, tmp_path
    )

    with guard_session_lifecycle(db_session):
        validated = validate_security_workflow_request(db_session, request)

    assert validated.request is not request
    assert validated.request.security_request is not request.security_request
    assert validated.task is task
    assert validated.developer is developer
    assert validated.reviewer is reviewer
    assert validated.qa is qa
    assert validated.security is security
    assert validated.request.security_request.execution_context.workspace_root.name == str(
        task.project_id
    )
    assert db_session.in_transaction()


def test_security_preflight_uses_canonical_workspace_scalar(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Use the reconstructed Path rather than a forged pre-canonicalization scalar."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    context = request.security_request.execution_context.model_copy(
        update={"workspace_root": str(request.security_request.execution_context.workspace_root)}
    )
    nested = request.security_request.model_copy(update={"execution_context": context})
    forged = request.model_copy(update={"security_request": nested})

    with guard_session_lifecycle(db_session):
        validated = validate_security_workflow_request(db_session, forged)

    assert validated.task is task
    assert isinstance(validated.request.security_request.execution_context.workspace_root, Path)


def test_security_preflight_accepts_nullable_persistent_description(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Canonicalize a nullable stored task description to the bounded empty string."""
    task, _, _, _, _, request = persisted_security_workflow_request(
        db_session,
        tmp_path,
        task_overrides={"description": None},
    )

    with guard_session_lifecycle(db_session):
        validated = validate_security_workflow_request(db_session, request)

    assert task.description is None
    assert validated.request.security_request.task_description == ""


def test_security_preflight_does_not_claim_database_authenticates_source_bytes(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Authenticate the managed path while leaving caller-supplied source bytes unendorsed."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    source = request.security_request.affected_files[0]
    (request.security_request.execution_context.workspace_root / source.path).write_text(
        "different bytes in the managed workspace\n",
        encoding="utf-8",
    )

    validated = validate_security_workflow_request(db_session, request)

    assert validated.task is task
    assert validated.request.security_request.affected_files[0].content == source.content


@pytest.mark.parametrize("missing", ["task", "developer", "reviewer", "qa", "security"])
def test_security_preflight_rejects_missing_persistent_scope(
    db_session: Session,
    tmp_path: Path,
    missing: str,
) -> None:
    """Require the persistent task and all four independent agents."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    if missing == "task":
        missing_id = uuid4()
        context = request.security_request.execution_context.model_copy(
            update={"task_id": missing_id}
        )
        nested = request.security_request.model_copy(
            update={"task_id": missing_id, "execution_context": context}
        )
        forged = request.model_copy(update={"task_id": missing_id, "security_request": nested})
    else:
        forged = request.model_copy(update={f"{missing}_agent_id": uuid4()})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_SCOPE,
    )


def test_security_preflight_requires_waiting_security(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Reject every state outside the exact post-QA handoff."""
    task, _, _, _, _, request = persisted_security_workflow_request(
        db_session,
        tmp_path,
        task_overrides={"status": TaskStatus.WAITING_QA},
    )

    assert_rejected_without_side_effects(
        db_session,
        task,
        request,
        SecurityWorkflowErrorCode.INVALID_STATE,
    )


def test_security_preflight_preserves_developer_assignment(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Keep the original Developer assigned during independent Security review."""
    task, _, reviewer, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    task.assigned_agent_id = reviewer.id
    db_session.flush()

    assert_rejected_without_side_effects(
        db_session,
        task,
        request,
        SecurityWorkflowErrorCode.INVALID_SCOPE,
    )


@pytest.mark.parametrize(
    ("kind", "overrides", "code"),
    [
        ("developer", {"role": "Reviewer"}, "INVALID_ROLE"),
        ("reviewer", {"role": "Developer"}, "INVALID_ROLE"),
        ("qa", {"role": "Reviewer"}, "INVALID_ROLE"),
        ("security", {"role": "QA"}, "INVALID_ROLE"),
        ("developer", {"status": AgentStatus.OFFLINE}, "INVALID_AGENT"),
        ("reviewer", {"status": AgentStatus.BLOCKED}, "INVALID_AGENT"),
        ("qa", {"status": AgentStatus.OFFLINE}, "INVALID_AGENT"),
        ("security", {"status": AgentStatus.BLOCKED}, "INVALID_AGENT"),
    ],
)
def test_security_preflight_requires_exact_active_persistent_roles(
    db_session: Session,
    tmp_path: Path,
    kind: str,
    overrides: dict[str, object],
    code: str,
) -> None:
    """Require exact active Developer, Reviewer, QA, and Security rows."""
    task, _, _, _, _, request = persisted_security_workflow_request(
        db_session,
        tmp_path,
        **{f"{kind}_overrides": overrides},
    )

    assert_rejected_without_side_effects(
        db_session,
        task,
        request,
        SecurityWorkflowErrorCode(code),
    )


@pytest.mark.parametrize("field", ["reviewer_agent_id", "qa_agent_id", "security_agent_id"])
def test_security_preflight_rejects_reused_persistent_uuid(
    db_session: Session,
    tmp_path: Path,
    field: str,
) -> None:
    """Prevent one database identity from occupying two workflow roles."""
    task, developer, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    forged = request.model_copy(update={field: developer.id})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_INPUT,
    )


@pytest.mark.parametrize("field", ["reviewer_id", "qa_id", "security_id"])
def test_security_preflight_rejects_reused_nested_slug(
    db_session: Session,
    tmp_path: Path,
    field: str,
) -> None:
    """Prevent one declared slug from occupying two Security handoff roles."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    nested = request.security_request.model_copy(update={field: "developer-01"})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_INPUT,
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("developer_id", "other-developer", "INVALID_SCOPE"),
        ("reviewer_id", "other-reviewer", "INVALID_SCOPE"),
        ("qa_id", "other-qa", "INVALID_SCOPE"),
        ("security_id", "other-security", "INVALID_SCOPE"),
        ("project_id", uuid4(), "INVALID_SCOPE"),
        ("task_id", uuid4(), "INVALID_INPUT"),
        ("correlation_id", uuid4(), "INVALID_INPUT"),
    ],
)
def test_security_preflight_rejects_nested_identity_and_scope_mismatch(
    db_session: Session,
    tmp_path: Path,
    field: str,
    value: object,
    code: str,
) -> None:
    """Bind nested Security work to exact persisted and correlation scope."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    nested = request.security_request.model_copy(update={field: value})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode(code),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "other-security"),
        ("role", "Reviewer"),
        ("status", AgentStatus.OFFLINE),
        ("name", "Forged Security"),
        ("department", "engineering"),
        ("seniority", AgentSeniority.PRINCIPAL),
        ("autonomy_level", 1),
        ("reputation_score", Decimal("0.7000")),
        ("reliability_score", Decimal("0.8000")),
    ],
)
def test_security_preflight_rejects_profile_persistence_mismatch(
    db_session: Session,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Prevent Security declarations from diverging from the database identity."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    profile = request.security_request.profile.model_copy(update={field: value})
    nested = request.security_request.model_copy(update={"profile": profile})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_SCOPE,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_title", "Different title"),
        ("task_description", "Different description"),
        ("acceptance_criteria", ("Different criterion",)),
    ],
)
def test_security_preflight_rejects_persistent_task_text_mismatch(
    db_session: Session,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Treat persisted task text as the authenticated handoff contract."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    nested = request.security_request.model_copy(update={field: value})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_SCOPE,
    )


@pytest.mark.parametrize("case", ["agent", "task", "project", "correlation", "workspace", "tools"])
def test_security_preflight_rejects_execution_context_mismatch(
    db_session: Session,
    tmp_path: Path,
    case: str,
) -> None:
    """Authenticate exact Security identity, task, project, correlation, and workspace scope."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    context_changes: dict[str, dict[str, object]] = {
        "agent": {"agent_id": "other-security"},
        "task": {"task_id": uuid4()},
        "project": {"project_id": uuid4()},
        "correlation": {"correlation_id": uuid4()},
        "workspace": {"workspace_root": tmp_path},
        "tools": {"declared_tool_ids": frozenset({"read_file"})},
    }
    changes: dict[str, object] = context_changes[case]
    context = request.security_request.execution_context.model_copy(update=changes)
    nested = request.security_request.model_copy(update={"execution_context": context})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        (
            SecurityWorkflowErrorCode.INVALID_INPUT
            if case == "correlation"
            else SecurityWorkflowErrorCode.INVALID_SCOPE
        ),
    )


@pytest.mark.parametrize("case", ["missing-path", "diff-path"])
def test_security_preflight_rejects_affected_file_scope_mismatch(
    db_session: Session,
    tmp_path: Path,
    case: str,
) -> None:
    """Bind declared normalized source paths to the managed workspace and reviewed diff."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    if case == "missing-path":
        affected = request.security_request.affected_files[0].model_copy(
            update={"path": "src/missing.py"}
        )
        changes: dict[str, object] = {"affected_files": (affected,)}
    else:
        changes = {"diff": "--- a/src/other.py\n+++ b/src/other.py\n@@ -1 +1 @@\n-old\n+new\n"}
    nested = request.security_request.model_copy(update=changes)
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_SCOPE,
    )


@pytest.mark.parametrize("case", ["failed-qa", "failed-test", "truncated-test"])
def test_security_preflight_requires_successful_qa_and_test_evidence(
    db_session: Session,
    tmp_path: Path,
    case: str,
) -> None:
    """Reject failed QA decisions and incomplete deterministic test evidence."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    if case == "failed-qa":
        qa_result = request.security_request.qa_result.model_copy(
            update={"decision": QADecision.FAILED}
        )
    else:
        test = request.security_request.tests[0].model_copy(
            update={
                "status": (
                    CommandTerminalStatus.FAILED
                    if case == "failed-test"
                    else CommandTerminalStatus.SUCCEEDED
                ),
                "exit_code": 1 if case == "failed-test" else 0,
                "truncated": case == "truncated-test",
            }
        )
        qa_result = request.security_request.qa_result.model_copy(update={"tests": (test,)})
    nested = request.security_request.model_copy(
        update={"qa_result": qa_result, "tests": qa_result.tests}
    )
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_INPUT,
    )


@pytest.mark.parametrize(
    "permissions",
    [
        frozenset({Permission.GIT_READ.value}),
        frozenset({Permission.FILESYSTEM_READ.value, Permission.FILESYSTEM_WRITE.value}),
    ],
)
def test_security_preflight_rejects_invalid_security_authority(
    db_session: Session,
    tmp_path: Path,
    permissions: frozenset[str],
) -> None:
    """Require the existing bounded read-only Security authority contract."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    profile = request.security_request.profile.model_copy(update={"permission_ids": permissions})
    nested = request.security_request.model_copy(update={"profile": profile})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_AGENT,
    )


def test_security_preflight_rejects_mutable_forged_capability_declarations(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Check raw nested types before serialization can freeze forged capabilities."""
    task, _, _, _, _, request = persisted_security_workflow_request(db_session, tmp_path)
    profile = request.security_request.profile.model_copy(
        update={"tool_ids": list(request.security_request.profile.tool_ids)}
    )
    nested = request.security_request.model_copy(update={"profile": profile})
    forged = request.model_copy(update={"security_request": nested})

    assert_rejected_without_side_effects(
        db_session,
        task,
        forged,
        SecurityWorkflowErrorCode.INVALID_INPUT,
    )
