"""Real-PostgreSQL tests for the Phase 18 Security read authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from core.enums import (
    AgentRunStatus,
    AgentStatus,
    AuditActorType,
    Permission,
    TaskStatus,
    ToolRiskLevel,
)
from core.permissions import PermissionOutcome, PermissionPolicyError, PolicyRequest
from core.tasks.state_machine import TaskStateMachine
from core.workflows import SecurityWorkflowRequest
from infrastructure.database.models import Agent, AgentPermission, AgentRun, Task
from infrastructure.permissions import (
    SECURITY_READ_CAPABILITIES,
    SQLAlchemySecurityPermissionPolicy,
)
from tests.workflows.security_factories import persisted_security_workflow_request

pytest_plugins = ("tests.database.conftest",)


@dataclass(frozen=True, slots=True)
class SecurityPolicySetup:
    """Persisted authority and canonical request for one Security run."""

    task: Task
    developer: Agent
    security: Agent
    run: AgentRun
    grant: AgentPermission
    request: SecurityWorkflowRequest


def _setup(
    session: Session,
    tmp_path: Path,
    *,
    tool_name: str = "read_file",
    grant_project: bool = True,
) -> SecurityPolicySetup:
    task, developer, _, _, security, request = persisted_security_workflow_request(
        session, tmp_path
    )
    run = AgentRun(agent=security, task=task, status=AgentRunStatus.RUNNING, iteration=1)
    session.add(run)
    session.flush()

    _, permissions = SECURITY_READ_CAPABILITIES[tool_name]
    permission = next(iter(permissions))
    grant = AgentPermission(
        agent=security,
        project_id=task.project_id if grant_project else None,
        permission=permission,
        granted_by_actor_type=AuditActorType.HUMAN,
        granted_by_actor_id="security-platform-administrator",
        reason="Bounded Phase 18 Security read authority.",
    )
    session.add(grant)
    session.flush()

    context = request.security_request.execution_context.model_copy(update={"agent_run_id": run.id})
    security_request = request.security_request.model_copy(update={"execution_context": context})
    request = request.model_copy(update={"security_request": security_request})
    return SecurityPolicySetup(task, developer, security, run, grant, request)


def _policy_request(
    setup: SecurityPolicySetup,
    capability_name: str,
    **overrides: object,
) -> PolicyRequest:
    context = setup.request.security_request.execution_context
    risk_level, permissions = SECURITY_READ_CAPABILITIES[capability_name]
    values: dict[str, object] = {
        "agent_id": context.agent_id,
        "agent_run_id": context.agent_run_id,
        "project_id": context.project_id,
        "task_id": context.task_id,
        "tool_name": capability_name,
        "risk_level": risk_level,
        "required_permissions": permissions,
        "correlation_id": context.correlation_id,
    }
    values.update(overrides)
    return PolicyRequest.model_validate(values, strict=True)


@pytest.mark.parametrize("tool_name", tuple(SECURITY_READ_CAPABILITIES))
@pytest.mark.parametrize("grant_project", [True, False])
def test_security_policy_allows_only_exact_active_read_capabilities(
    db_session: Session,
    tmp_path: Path,
    tool_name: str,
    grant_project: bool,
) -> None:
    """Allow each declared read capability with a matching live grant."""
    setup = _setup(
        db_session,
        tmp_path,
        tool_name=tool_name,
        grant_project=grant_project,
    )

    decision = SQLAlchemySecurityPermissionPolicy(db_session).evaluate(
        _policy_request(setup, tool_name), datetime.now(UTC)
    )

    assert decision.outcome is PermissionOutcome.ALLOW


@pytest.mark.parametrize(
    ("tool_name", "overrides"),
    [
        ("read_file", {"tool_name": "write_file"}),
        ("read_file", {"risk_level": ToolRiskLevel.MEDIUM}),
        (
            "read_file",
            {
                "required_permissions": frozenset(
                    {Permission.FILESYSTEM_READ, Permission.FILESYSTEM_WRITE}
                )
            },
        ),
        ("git_diff", {"required_permissions": frozenset({Permission.GIT_WRITE})}),
        (
            "read_file",
            {"required_permissions": frozenset({Permission.DEPLOYMENT_PRODUCTION})},
        ),
    ],
)
def test_security_policy_denies_unknown_or_noncanonical_capabilities(
    db_session: Session,
    tmp_path: Path,
    tool_name: str,
    overrides: dict[str, object],
) -> None:
    """Deny unknown, elevated, write, shell, and deployment authority."""
    setup = _setup(db_session, tmp_path, tool_name=tool_name)

    decision = SQLAlchemySecurityPermissionPolicy(db_session).evaluate(
        _policy_request(setup, tool_name, **overrides), datetime.now(UTC)
    )

    assert decision.outcome is PermissionOutcome.DENY


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-grant",
        "revoked-grant",
        "expired-grant",
        "wrong-role",
        "inactive-security",
        "excess-autonomy",
        "finished-run",
        "wrong-task-state",
        "inactive-developer",
        "self-review",
    ],
)
def test_security_policy_denies_invalid_persisted_authority(
    db_session: Session,
    tmp_path: Path,
    mutation: str,
) -> None:
    """Keep Security authority bound to one independent active persisted scope."""
    setup = _setup(db_session, tmp_path)
    grant = setup.grant
    evaluated_at = datetime.now(UTC)
    if mutation == "missing-grant":
        db_session.delete(grant)
    elif mutation == "revoked-grant":
        grant.revoked_at = datetime.now(UTC)
    elif mutation == "expired-grant":
        grant.expires_at = evaluated_at + timedelta(seconds=1)
        evaluated_at += timedelta(seconds=2)
    elif mutation == "wrong-role":
        setup.security.role = "Developer"
    elif mutation == "inactive-security":
        setup.security.status = AgentStatus.OFFLINE
    elif mutation == "excess-autonomy":
        setup.security.autonomy_level = 2
    elif mutation == "finished-run":
        setup.run.status = AgentRunStatus.SUCCEEDED
    elif mutation == "wrong-task-state":
        TaskStateMachine(db_session).transition(
            setup.task,
            TaskStatus.WAITING_HUMAN,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            reason="Security authority test state change.",
        )
    elif mutation == "inactive-developer":
        setup.developer.status = AgentStatus.OFFLINE
    else:
        setup.task.assigned_agent_id = setup.security.id
    db_session.flush()

    decision = SQLAlchemySecurityPermissionPolicy(db_session).evaluate(
        _policy_request(setup, "read_file"), evaluated_at
    )

    assert decision.outcome is PermissionOutcome.DENY


@pytest.mark.parametrize(
    "overrides",
    [
        {"agent_run_id": uuid4()},
        {"task_id": uuid4()},
        {"project_id": uuid4()},
        {"agent_id": "security-other"},
    ],
)
def test_security_policy_denies_forged_request_scope(
    db_session: Session,
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    """Deny request identifiers that do not match the persisted delegation."""
    setup = _setup(db_session, tmp_path)

    decision = SQLAlchemySecurityPermissionPolicy(db_session).evaluate(
        _policy_request(setup, "read_file", **overrides), datetime.now(UTC)
    )

    assert decision.outcome is PermissionOutcome.DENY


def test_security_policy_never_owns_session_lifecycle(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Leave transaction ownership with the workflow caller."""
    setup = _setup(db_session, tmp_path)
    policy = SQLAlchemySecurityPermissionPolicy(db_session)

    with (
        patch.object(db_session, "commit", side_effect=AssertionError("commit called")),
        patch.object(db_session, "rollback", side_effect=AssertionError("rollback called")),
        patch.object(db_session, "close", side_effect=AssertionError("close called")),
    ):
        policy.evaluate(_policy_request(setup, "read_file"), datetime.now(UTC))


def test_security_policy_sanitizes_database_failures(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Do not expose database details through policy failures."""
    setup = _setup(db_session, tmp_path)
    marker = "secret-security-policy-database-marker"

    with (
        patch.object(db_session, "scalar", side_effect=RuntimeError(marker)),
        pytest.raises(PermissionPolicyError, match="Permission policy unavailable") as error,
    ):
        SQLAlchemySecurityPermissionPolicy(db_session).evaluate(
            _policy_request(setup, "read_file"), datetime.now(UTC)
        )

    assert marker not in str(error.value)
