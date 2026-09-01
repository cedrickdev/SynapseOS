"""Real-PostgreSQL tests for the delegated Phase 17 QA permission boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
from core.permissions import PermissionOutcome, PolicyRequest
from core.tasks.state_machine import TaskStateMachine
from infrastructure.permissions import SQLAlchemyQAPermissionPolicy
from tests.qa.integration_fixtures import ConcreteQASetup, concrete_qa_setup

pytest_plugins = ("tests.database.conftest",)


def _policy_request(setup: ConcreteQASetup, **overrides: object) -> PolicyRequest:
    context = setup.request.qa_request.execution_context
    values: dict[str, object] = {
        "agent_id": context.agent_id,
        "agent_run_id": context.agent_run_id,
        "project_id": context.project_id,
        "task_id": context.task_id,
        "tool_name": "run_command_profile",
        "risk_level": ToolRiskLevel.HIGH,
        "required_permissions": frozenset(
            {Permission.SHELL_EXECUTE, Permission.TESTS_EXECUTE}
        ),
        "correlation_id": context.correlation_id,
    }
    values.update(overrides)
    return PolicyRequest.model_validate(values, strict=True)


def test_exact_delegated_qa_scope_allows_bounded_test_profile(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Allow the non-author QA agent only under its exact persisted test scope."""
    setup = concrete_qa_setup(db_session, tmp_path)

    decision = SQLAlchemyQAPermissionPolicy(db_session).evaluate(
        _policy_request(setup), datetime.now(UTC)
    )

    assert decision.outcome is PermissionOutcome.ALLOW


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-task-state",
        "wrong-role",
        "inactive-agent",
        "finished-run",
        "self-assigned-task",
    ],
)
def test_delegated_qa_scope_denies_any_persistent_authority_mismatch(
    db_session: Session,
    tmp_path: Path,
    mutation: str,
) -> None:
    """Keep the assignment exception closed to one active independent QA stage."""
    setup = concrete_qa_setup(db_session, tmp_path)
    qa = setup.run.agent
    if mutation == "wrong-task-state":
        TaskStateMachine(db_session).transition(
            setup.task,
            TaskStatus.WAITING_SECURITY,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            reason="Advance beyond the delegated QA stage for policy verification.",
        )
    elif mutation == "wrong-role":
        qa.role = "Developer"
    elif mutation == "inactive-agent":
        qa.status = AgentStatus.OFFLINE
    elif mutation == "finished-run":
        setup.run.status = AgentRunStatus.SUCCEEDED
    else:
        setup.task.assigned_agent_id = qa.id
    db_session.flush()

    decision = SQLAlchemyQAPermissionPolicy(db_session).evaluate(
        _policy_request(setup), datetime.now(UTC)
    )

    assert decision.outcome is PermissionOutcome.DENY


@pytest.mark.parametrize(
    "overrides",
    [
        {"tool_name": "read_file", "risk_level": ToolRiskLevel.LOW},
        {"risk_level": ToolRiskLevel.MEDIUM},
        {"required_permissions": frozenset({Permission.TESTS_EXECUTE})},
    ],
)
def test_delegated_qa_policy_denies_noncanonical_capabilities(
    db_session: Session,
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    """Never turn the QA delegation into general tool or shell authority."""
    setup = concrete_qa_setup(db_session, tmp_path)

    decision = SQLAlchemyQAPermissionPolicy(db_session).evaluate(
        _policy_request(setup, **overrides), datetime.now(UTC)
    )

    assert decision.outcome is PermissionOutcome.DENY
