"""Unit tests for bounded control API contracts."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.control_api import (
    ControlPrincipal,
    ControlRole,
    LaunchWorkflowCommand,
    ProjectIntakeCommand,
)


def test_control_principal_requires_unique_bounded_roles() -> None:
    company_id = uuid4()
    principal = ControlPrincipal(
        actor_id="human-owner",
        company_id=company_id,
        roles=(ControlRole.OWNER, ControlRole.OPERATOR),
    )

    assert principal.roles == (ControlRole.OWNER, ControlRole.OPERATOR)
    with pytest.raises(ValidationError):
        ControlPrincipal(
            actor_id="human-owner",
            company_id=company_id,
            roles=(ControlRole.OWNER, ControlRole.OWNER),
        )


def test_commands_require_explicit_idempotency_and_correlation_ids() -> None:
    command_id = uuid4()
    correlation_id = uuid4()
    agent_id = uuid4()
    intake = ProjectIntakeCommand(
        command_id=command_id,
        correlation_id=correlation_id,
        idempotency_key="intake-001",
        name="Control API project",
        specification="Build the approved bounded workflow.",
        task_title="Run Engineering V1",
        assigned_agent_id=agent_id,
    )

    assert intake.command_id == command_id
    assert intake.correlation_id == correlation_id
    assert intake.assigned_agent_id == agent_id

    with pytest.raises(ValidationError):
        LaunchWorkflowCommand(
            command_id=uuid4(),
            correlation_id=uuid4(),
            idempotency_key="",
            project_id=uuid4(),
            task_id=uuid4(),
        )
