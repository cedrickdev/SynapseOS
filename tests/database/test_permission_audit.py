"""Real-PostgreSQL tests for append-only permission decision audits."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AuditActorType, AuditResult, Permission
from core.permissions import (
    PermissionAuditError,
    PermissionDecision,
    PermissionOutcome,
    PermissionReasonCode,
)
from infrastructure.database.models import AuditEvent
from infrastructure.permissions import SQLAlchemyPermissionAuditRecorder
from tests.database.permission_fixtures import PermissionScope, create_permission_scope


def _decision(
    scope: PermissionScope,
    outcome: PermissionOutcome,
    reason: PermissionReasonCode,
) -> PermissionDecision:
    request = scope.request(frozenset({Permission.FILESYSTEM_READ}))
    return PermissionDecision.from_request(
        request,
        outcome=outcome,
        required_permissions=request.required_permissions,
        reason_code=reason,
        safe_message="Permission decision completed.",
        evaluated_at=scope.now,
    )


def test_allow_decision_appends_sanitized_event(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    decision = _decision(scope, PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)

    SQLAlchemyPermissionAuditRecorder(db_session).record(decision)

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "PERMISSION_EVALUATED")
    )
    assert event is not None
    assert event.actor_type is AuditActorType.AGENT
    assert event.actor_id == scope.agent.slug
    assert event.project_id == scope.project.id
    assert event.task_id == scope.task.id
    assert event.agent_run_id == scope.run.id
    assert event.result is AuditResult.SUCCEEDED
    assert event.data == {
        "decision": "ALLOW",
        "required_permissions": ["filesystem.read"],
        "reason_code": "GRANTED",
    }


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (PermissionOutcome.DENY, PermissionReasonCode.MISSING_PERMISSION),
        (PermissionOutcome.ASK, PermissionReasonCode.AUTONOMY_APPROVAL_REQUIRED),
    ],
)
def test_non_allow_decisions_are_audited_as_denied(
    db_session: Session,
    outcome: PermissionOutcome,
    reason: PermissionReasonCode,
) -> None:
    scope = create_permission_scope(db_session)

    SQLAlchemyPermissionAuditRecorder(db_session).record(_decision(scope, outcome, reason))

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "PERMISSION_EVALUATED")
    )
    assert event is not None
    assert event.result is AuditResult.DENIED
    assert event.data["decision"] == outcome.value


def test_permission_audit_contains_no_unrelated_or_sensitive_data(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    secret = "secret-permission-audit-marker"
    scope.project.description = secret
    scope.task.description = secret

    SQLAlchemyPermissionAuditRecorder(db_session).record(
        _decision(scope, PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    )

    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "PERMISSION_EVALUATED")
    )
    assert event is not None
    assert secret not in repr(event.data)
    assert set(event.data) == {"decision", "required_permissions", "reason_code"}


def test_permission_audit_never_owns_session_lifecycle(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    recorder = SQLAlchemyPermissionAuditRecorder(db_session)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        recorder.record(_decision(scope, PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED))


def test_permission_audit_failure_is_sanitized(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    marker = "secret-permission-persistence-marker"

    with (
        patch.object(db_session, "flush", side_effect=RuntimeError(marker)),
        pytest.raises(PermissionAuditError, match="Permission audit is unavailable") as error,
    ):
        SQLAlchemyPermissionAuditRecorder(db_session).record(
            _decision(scope, PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
        )
    assert marker not in str(error.value)
