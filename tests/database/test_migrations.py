"""Alembic lifecycle tests against an isolated PostgreSQL database."""

from __future__ import annotations

import uuid

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command

EXPECTED_TABLES = {
    "agent_permissions",
    "agent_runs",
    "agent_scores",
    "agents",
    "audit_events",
    "decisions",
    "projects",
    "task_dependencies",
    "tasks",
    "tool_calls",
}


def _config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    return config


def test_migration_supports_upgrade_downgrade_and_second_upgrade(
    migration_database_url: str,
) -> None:
    config = _config(migration_database_url)

    command.upgrade(config, "20260825_0001")
    engine = create_engine(migration_database_url)
    try:
        assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES - {"agent_permissions"}
        project_id = uuid.uuid4()
        task_ids = [uuid.uuid4() for _ in range(4)]
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, status, created_at, updated_at) "
                    "VALUES (:id, 'Migration project', 'INTAKE', now(), now())"
                ),
                {"id": project_id},
            )
            for task_id, status in zip(
                task_ids, ["DRAFT", "REJECTED", "WAITING_HUMAN", "DONE"], strict=True
            ):
                connection.execute(
                    text(
                        "INSERT INTO tasks "
                        "(id, project_id, title, status, priority, acceptance_criteria, "
                        "max_iterations, iteration_count, created_at, updated_at) "
                        "VALUES (:id, :project_id, :title, :status, 'MEDIUM', '[]', "
                        "3, 0, now(), now())"
                    ),
                    {
                        "id": task_id,
                        "project_id": project_id,
                        "title": f"Task in {status}",
                        "status": status,
                    },
                )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(migration_database_url)
    try:
        assert "agent_permissions" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            statuses = connection.execute(
                text("SELECT status::text FROM tasks ORDER BY title")
            ).scalars()
            assert set(statuses) == {
                "BACKLOG",
                "CHANGES_REQUESTED",
                "WAITING_HUMAN",
                "COMPLETED",
            }
            enum_values = connection.execute(
                text(
                    "SELECT enumlabel FROM pg_enum "
                    "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE pg_type.typname = 'task_status' ORDER BY enumsortorder"
                )
            ).scalars()
            assert list(enum_values) == [
                "BACKLOG",
                "READY",
                "ASSIGNED",
                "IN_PROGRESS",
                "WAITING_REVIEW",
                "CHANGES_REQUESTED",
                "WAITING_QA",
                "WAITING_SECURITY",
                "BLOCKED",
                "WAITING_HUMAN",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            ]
            permission_values = connection.execute(
                text(
                    "SELECT enumlabel FROM pg_enum "
                    "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE pg_type.typname = 'permission' ORDER BY enumsortorder"
                )
            ).scalars()
            assert list(permission_values) == [
                "FILESYSTEM_READ",
                "FILESYSTEM_WRITE",
                "GIT_READ",
                "GIT_WRITE",
                "SHELL_EXECUTE",
                "TESTS_EXECUTE",
                "NETWORK_ACCESS",
                "DATABASE_READ",
                "DATABASE_WRITE",
                "DEPLOYMENT_STAGING",
                "DEPLOYMENT_PRODUCTION",
            ]
        with engine.begin() as connection:
            for status in ("WAITING_QA", "WAITING_SECURITY", "FAILED"):
                connection.execute(
                    text(
                        "INSERT INTO tasks "
                        "(id, project_id, title, status, priority, acceptance_criteria, "
                        "max_iterations, iteration_count, created_at, updated_at) "
                        "VALUES (:id, :project_id, :title, :status, 'MEDIUM', '[]', "
                        "3, 0, now(), now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "project_id": project_id,
                        "title": f"Phase 3 task in {status}",
                        "status": status,
                    },
                )
    finally:
        engine.dispose()

    command.downgrade(config, "20260825_0002")
    engine = create_engine(migration_database_url)
    try:
        assert "agent_permissions" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            permission_type_count = connection.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'permission'")
            ).scalar_one()
            assert permission_type_count == 0
    finally:
        engine.dispose()

    command.downgrade(config, "20260825_0001")
    engine = create_engine(migration_database_url)
    try:
        with engine.connect() as connection:
            statuses = connection.execute(
                text("SELECT status::text FROM tasks ORDER BY title")
            ).scalars()
            assert set(statuses) == {
                "DRAFT",
                "REJECTED",
                "WAITING_REVIEW",
                "WAITING_HUMAN",
                "DONE",
                "BLOCKED",
            }
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(migration_database_url)
    try:
        assert EXPECTED_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "head")
