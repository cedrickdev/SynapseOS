"""Real-PostgreSQL tests for scoped permission policy evaluation."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from core.enums import Permission
from core.permissions import PermissionOutcome, PermissionPolicyError, PermissionReasonCode
from infrastructure.database.models import Project
from infrastructure.permissions import SQLAlchemyPermissionPolicy
from tests.database.permission_fixtures import add_permission, create_permission_scope


def test_policy_allows_active_global_grant(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    add_permission(db_session, scope, Permission.FILESYSTEM_READ)

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(frozenset({Permission.FILESYSTEM_READ})),
        scope.now,
    )

    assert decision.outcome is PermissionOutcome.ALLOW
    assert decision.reason_code is PermissionReasonCode.GRANTED


def test_policy_allows_matching_project_grant(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    add_permission(
        db_session,
        scope,
        Permission.FILESYSTEM_READ,
        project=scope.project,
    )

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(frozenset({Permission.FILESYSTEM_READ})), scope.now
    )

    assert decision.outcome is PermissionOutcome.ALLOW


@pytest.mark.parametrize("grant_state", ["missing", "expired", "revoked", "other-project"])
def test_policy_denies_inactive_or_out_of_scope_grants(
    db_session: Session,
    grant_state: str,
) -> None:
    scope = create_permission_scope(db_session)
    if grant_state == "expired":
        add_permission(
            db_session,
            scope,
            Permission.FILESYSTEM_READ,
            expires_at=scope.now - timedelta(seconds=1),
        )
    elif grant_state == "revoked":
        add_permission(
            db_session,
            scope,
            Permission.FILESYSTEM_READ,
            revoked_at=scope.now,
        )
    elif grant_state == "other-project":
        other_project = Project(name="Other permission project")
        db_session.add(other_project)
        db_session.flush()
        add_permission(
            db_session,
            scope,
            Permission.FILESYSTEM_READ,
            project=other_project,
        )

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(frozenset({Permission.FILESYSTEM_READ})), scope.now
    )

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.reason_code is PermissionReasonCode.MISSING_PERMISSION


def test_policy_denies_when_one_required_permission_is_missing(db_session: Session) -> None:
    scope = create_permission_scope(db_session, autonomy_level=3)
    add_permission(db_session, scope, Permission.FILESYSTEM_READ)

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(frozenset({Permission.FILESYSTEM_READ, Permission.NETWORK_ACCESS})),
        scope.now,
    )

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.reason_code is PermissionReasonCode.MISSING_PERMISSION


def test_policy_denies_forged_execution_scope(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    add_permission(db_session, scope, Permission.FILESYSTEM_READ)

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(
            frozenset({Permission.FILESYSTEM_READ}),
            project_id=uuid.uuid4(),
        ),
        scope.now,
    )

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.reason_code is PermissionReasonCode.INVALID_SCOPE


@pytest.mark.parametrize(
    ("permission", "autonomy_level", "expected"),
    [
        (Permission.FILESYSTEM_READ, 0, PermissionOutcome.ALLOW),
        (Permission.FILESYSTEM_WRITE, 0, PermissionOutcome.ASK),
        (Permission.GIT_WRITE, 1, PermissionOutcome.ASK),
        (Permission.NETWORK_ACCESS, 2, PermissionOutcome.ASK),
        (Permission.DEPLOYMENT_STAGING, 3, PermissionOutcome.ALLOW),
    ],
)
def test_policy_applies_minimum_autonomy_after_grant(
    db_session: Session,
    permission: Permission,
    autonomy_level: int,
    expected: PermissionOutcome,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=autonomy_level)
    add_permission(db_session, scope, permission)

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(frozenset({permission})), scope.now
    )

    assert decision.outcome is expected


def test_production_permission_always_requires_human_approval(db_session: Session) -> None:
    scope = create_permission_scope(db_session, autonomy_level=5)
    add_permission(db_session, scope, Permission.DEPLOYMENT_PRODUCTION)

    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(frozenset({Permission.DEPLOYMENT_PRODUCTION})), scope.now
    )

    assert decision.outcome is PermissionOutcome.ASK
    assert decision.reason_code is PermissionReasonCode.HUMAN_APPROVAL_REQUIRED


def test_policy_never_owns_session_lifecycle(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    add_permission(db_session, scope, Permission.FILESYSTEM_READ)
    policy = SQLAlchemyPermissionPolicy(db_session)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        policy.evaluate(scope.request(frozenset({Permission.FILESYSTEM_READ})), scope.now)


def test_database_failure_is_sanitized(db_session: Session) -> None:
    scope = create_permission_scope(db_session)
    marker = "secret-policy-database-marker"
    with (
        patch.object(db_session, "scalar", side_effect=RuntimeError(marker)),
        pytest.raises(PermissionPolicyError, match="Permission policy is unavailable") as error,
    ):
        SQLAlchemyPermissionPolicy(db_session).evaluate(
            scope.request(frozenset({Permission.FILESYSTEM_READ})), scope.now
        )
    assert marker not in str(error.value)
