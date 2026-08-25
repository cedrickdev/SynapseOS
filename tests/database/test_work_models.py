"""ORM contract tests for organization and work models."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.database.models import Agent, Project, Task, TaskDependency


def test_work_models_expose_required_columns() -> None:
    assert set(Agent.__table__.columns.keys()) == {
        "id",
        "name",
        "slug",
        "role",
        "department",
        "seniority",
        "status",
        "autonomy_level",
        "reputation_score",
        "reliability_score",
        "created_at",
        "updated_at",
    }
    assert set(Project.__table__.columns.keys()) == {
        "id",
        "name",
        "description",
        "status",
        "client_name",
        "created_at",
        "updated_at",
    }
    assert set(Task.__table__.columns.keys()) == {
        "id",
        "project_id",
        "parent_task_id",
        "title",
        "description",
        "status",
        "priority",
        "assigned_agent_id",
        "acceptance_criteria",
        "max_iterations",
        "iteration_count",
        "created_at",
        "updated_at",
    }
    assert set(TaskDependency.__table__.columns.keys()) == {
        "id",
        "task_id",
        "depends_on_task_id",
        "created_at",
    }


def test_task_uses_postgresql_jsonb_for_acceptance_criteria() -> None:
    assert isinstance(Task.__table__.c.acceptance_criteria.type, JSONB)


def test_dependency_edges_are_the_only_cascading_task_foreign_keys() -> None:
    dependency_fks = {fk.parent.name: fk.ondelete for fk in TaskDependency.__table__.foreign_keys}
    assert dependency_fks == {"task_id": "CASCADE", "depends_on_task_id": "CASCADE"}

    task_fks = {fk.parent.name: fk.ondelete for fk in Task.__table__.foreign_keys}
    assert task_fks == {
        "project_id": "RESTRICT",
        "parent_task_id": "RESTRICT",
        "assigned_agent_id": "RESTRICT",
    }


def test_work_models_define_integrity_constraints() -> None:
    agent_table = cast(Table, Agent.__table__)
    task_table = cast(Table, Task.__table__)
    dependency_table = cast(Table, TaskDependency.__table__)
    agent_checks = {constraint.name for constraint in agent_table.constraints}
    task_checks = {constraint.name for constraint in task_table.constraints}
    dependency_constraints = {constraint.name for constraint in dependency_table.constraints}
    assert "ck_agents_autonomy_level_range" in agent_checks
    assert "ck_agents_reputation_score_range" in agent_checks
    assert "ck_agents_reliability_score_range" in agent_checks
    assert "ck_tasks_iteration_bounds" in task_checks
    assert "uq_task_dependencies_task_id" in dependency_constraints
    assert "ck_task_dependencies_no_self_dependency" in dependency_constraints
