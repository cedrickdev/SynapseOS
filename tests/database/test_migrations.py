"""Alembic lifecycle tests against an isolated PostgreSQL database."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast

from alembic.config import Config
from sqlalchemy import Numeric, create_engine, inspect, text

from alembic import command

EXPECTED_TABLES = {
    "agent_capability_metric_evidence",
    "agent_genome_evidence",
    "agent_genome_run_snapshots",
    "agent_performance_metric_evidence",
    "agent_permissions",
    "agent_runs",
    "agent_scores",
    "agents",
    "approvals",
    "audit_events",
    "decisions",
    "projects",
    "pull_request_reviews",
    "pull_requests",
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
        phase_2_tables = EXPECTED_TABLES - {
            "agent_capability_metric_evidence",
            "agent_genome_evidence",
            "agent_genome_run_snapshots",
            "agent_performance_metric_evidence",
            "agent_permissions",
            "approvals",
            "pull_request_reviews",
            "pull_requests",
        }
        assert set(inspect(engine).get_table_names()) >= phase_2_tables
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


def test_genome_evidence_migration_has_reversible_table_and_enums(
    migration_database_url: str,
) -> None:
    config = _config(migration_database_url)
    command.upgrade(config, "head")
    engine = create_engine(migration_database_url)
    try:
        assert "agent_genome_evidence" in inspect(engine).get_table_names()
        numeric_value = next(
            column
            for column in inspect(engine).get_columns("agent_genome_evidence")
            if column["name"] == "numeric_value"
        )
        numeric_type = cast(Numeric[Decimal], numeric_value["type"])
        assert numeric_type.precision == 20
        assert numeric_type.scale == 8
    finally:
        engine.dispose()

    command.downgrade(config, "20260913_0009")
    engine = create_engine(migration_database_url)
    try:
        assert "agent_genome_evidence" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            enum_count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_type WHERE typname IN "
                    "('genome_evidence_source_type', 'genome_evidence_signal', "
                    "'genome_evidence_outcome', 'genome_evidence_unit')"
                )
            ).scalar_one()
            assert enum_count == 0
    finally:
        engine.dispose()

    command.upgrade(config, "head")


def test_capability_scoring_migration_is_reversible(migration_database_url: str) -> None:
    config = _config(migration_database_url)
    command.upgrade(config, "head")


def test_component_trust_registry_migration_is_reversible(
    migration_database_url: str,
) -> None:
    config = _config(migration_database_url)
    command.upgrade(config, "head")
    engine = create_engine(migration_database_url)
    try:
        inspector = inspect(engine)
        assert "component_trust_manifests" in inspector.get_table_names()
        assert {
            "component_id",
            "component_type",
            "requested_capabilities",
            "trust_level",
            "last_scan_at",
            "scan_policy_version",
        } <= {column["name"] for column in inspector.get_columns("component_trust_manifests")}
    finally:
        engine.dispose()

    command.downgrade(config, "20260923_0016")
    engine = create_engine(migration_database_url)
    try:
        assert "component_trust_manifests" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            enum_count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_type WHERE typname IN "
                    "('component_type', 'component_trust_level')"
                )
            ).scalar_one()
            assert enum_count == 0
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(migration_database_url)
    try:
        inspector = inspect(engine)
        assert "agent_capability_metric_evidence" in inspector.get_table_names()
        metric_columns = {
            column["name"] for column in inspector.get_columns("agent_capability_metrics")
        }
        assert {"scoring_policy", "total_weight", "agent_genome_id", "agent_id"} <= metric_columns
        with engine.connect() as connection:
            policy_values = connection.execute(
                text(
                    "SELECT enumlabel FROM pg_enum "
                    "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE pg_type.typname = 'capability_scoring_policy' "
                    "ORDER BY enumsortorder"
                )
            ).scalars()
            assert list(policy_values) == ["BAYESIAN_V1"]
    finally:
        engine.dispose()

    command.downgrade(config, "20260913_0010")
    engine = create_engine(migration_database_url)
    try:
        inspector = inspect(engine)
        assert "agent_capability_metric_evidence" not in inspector.get_table_names()
        metric_columns = {
            column["name"] for column in inspector.get_columns("agent_capability_metrics")
        }
        assert {
            "scoring_policy",
            "total_weight",
            "agent_genome_id",
            "agent_id",
        }.isdisjoint(metric_columns)
        with engine.connect() as connection:
            enum_count = connection.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'capability_scoring_policy'")
            ).scalar_one()
            assert enum_count == 0
    finally:
        engine.dispose()

    command.upgrade(config, "head")
