"""Alembic lifecycle tests against an isolated PostgreSQL database."""

from __future__ import annotations

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command

EXPECTED_TABLES = {
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

    command.upgrade(config, "head")
    engine = create_engine(migration_database_url)
    try:
        assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(migration_database_url)
    try:
        assert EXPECTED_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "head")
