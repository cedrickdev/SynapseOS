"""Real-PostgreSQL tests for scoped agent permission grants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Enum, Table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AgentSeniority, AuditActorType, Permission
from infrastructure.database.models import Agent, AgentPermission, Project


def test_agent_permission_has_required_columns_and_indexes() -> None:
    """Catch a schema that cannot represent scoped, expiring, revocable authority."""
    table = cast(Table, AgentPermission.__table__)

    assert set(table.columns.keys()) == {
        "id",
        "agent_id",
        "permission",
        "project_id",
        "granted_by_actor_type",
        "granted_by_actor_id",
        "reason",
        "expires_at",
        "revoked_at",
        "created_at",
    }
    assert cast(Enum, table.c.permission.type).name == "permission"
    assert {
        "ix_agent_permissions_lookup",
        "ix_agent_permissions_expires_at",
        "ix_agent_permissions_revoked_at",
        "uq_agent_permissions_global",
        "uq_agent_permissions_project",
    }.issubset({index.name for index in table.indexes})


def _scope(session: Session) -> tuple[Agent, Project]:
    agent = Agent(
        name="Permission Agent",
        slug="permission-agent",
        role="Developer",
        department="engineering",
        seniority=AgentSeniority.ENGINEER,
    )
    project = Project(name="Permission Project")
    session.add_all([agent, project])
    session.flush()
    return agent, project


def _grant(agent: Agent, **changes: object) -> AgentPermission:
    values: dict[str, object] = {
        "agent": agent,
        "permission": Permission.FILESYSTEM_READ,
        "granted_by_actor_type": AuditActorType.HUMAN,
        "granted_by_actor_id": "platform-admin",
        "reason": "Required for an approved repository task.",
    }
    values.update(changes)
    return AgentPermission(**values)


def test_agent_actor_cannot_persist_its_own_grant(db_session: Session) -> None:
    agent, _ = _scope(db_session)
    db_session.add(_grant(agent, granted_by_actor_type=AuditActorType.AGENT))

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("timestamp_field", ["expires_at", "revoked_at"])
def test_permission_timestamps_cannot_precede_creation(
    db_session: Session,
    timestamp_field: str,
) -> None:
    agent, _ = _scope(db_session)
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    db_session.add(
        _grant(
            agent,
            created_at=created_at,
            **{timestamp_field: created_at - timedelta(seconds=1)},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_global_permission_is_rejected(db_session: Session) -> None:
    agent, _ = _scope(db_session)
    db_session.add_all([_grant(agent), _grant(agent)])

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_project_permission_is_rejected(db_session: Session) -> None:
    agent, project = _scope(db_session)
    db_session.add_all([_grant(agent, project=project), _grant(agent, project=project)])

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_permission_can_be_scoped_to_different_projects(db_session: Session) -> None:
    agent, project = _scope(db_session)
    another_project = Project(name="Another Permission Project")
    db_session.add(another_project)
    db_session.flush()
    db_session.add_all([_grant(agent, project=project), _grant(agent, project=another_project)])

    db_session.flush()
