# Phase 2 Fundamental Data Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the nine Phase 2 SQLAlchemy entities, PostgreSQL migration, append-only history
protection, and real-PostgreSQL tests without implementing Phase 3 behavior.

**Architecture:** Shared enums live in `core`; common ORM primitives live in `database/base.py`;
models are grouped by domain; Alembic consumes model metadata directly; append-only behavior is
enforced by repositories and a global session guard. Tests create ephemeral PostgreSQL databases,
apply Alembic, and isolate each test with an outer transaction and savepoints.

**Tech Stack:** Python 3.12, SQLAlchemy 2, PostgreSQL 16, psycopg 3, Alembic, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-25-phase-2-data-model-design.md`

## Global Constraints

- Implement Phase 2 only; do not add task transitions, LLM logic, autonomous agents, or CRUD APIs.
- Use English for code, comments, docstrings, documentation, and migration names.
- Use UUID primary keys, UTC `TIMESTAMPTZ`, explicit enums, `NUMERIC(5,4)`, and PostgreSQL JSONB.
- Use real PostgreSQL for every database test; never use SQLite or `metadata.create_all()`.
- Historical references use `ON DELETE RESTRICT`; only `TaskDependency` edges cascade.
- `AgentScore` and `AuditEvent` are append-only at the application level.
- Follow RED, GREEN, REFACTOR for every behavior.
- Do not commit or push without explicit user authorization.

---

### Task 1: ORM primitives and shared enums

**Files:**
- Create: `core/enums.py`
- Create: `infrastructure/database/base.py`
- Create: `tests/database/test_base_and_enums.py`

**Interfaces:**
- Produces `Base`, `UUIDPrimaryKeyMixin`, `CreatedAtMixin`, `TimestampMixin`.
- Produces the twelve approved `StrEnum` classes from the design specification.

- [ ] Write tests asserting every enum's exact persisted value and that a minimal class inheriting
  the common mixins exposes UUID and timezone-aware timestamp columns.
- [ ] Run `.venv/bin/pytest tests/database/test_base_and_enums.py -v` and verify collection fails
  because the modules do not exist.
- [ ] Implement enums with uppercase string values and metadata naming conventions for indexes,
  unique constraints, checks, foreign keys, and primary keys.
- [ ] Implement typed mapped UUID/timestamp mixins using `uuid.uuid4`, `DateTime(timezone=True)`,
  `server_default=func.now()`, and `onupdate=func.now()` where applicable.
- [ ] Re-run the focused test and keep the full suite green.

### Task 2: Agent, project, task, and dependency models

**Files:**
- Create: `infrastructure/database/models/organization.py`
- Create: `infrastructure/database/models/work.py`
- Create: `infrastructure/database/models/__init__.py`
- Create: `tests/database/test_work_models.py`

**Interfaces:**
- Produces `Agent`, `Project`, `Task`, and `TaskDependency` with typed relationships.
- `Task.acceptance_criteria` is `MutableList.as_mutable(JSONB)`.

- [ ] Write ORM contract tests for project tasks, parent/children tasks, assignment, dependency
  edges, constraints, indexes, and PostgreSQL column types.
- [ ] Run the focused contract tests and verify they fail because the models are absent.
- [ ] Implement the four models with the exact fields, indexes, checks, uniqueness, and delete
  policies from the design.
- [ ] Run the focused contract tests and the existing health test until green.
- [ ] Defer database-enforced behavior to Task 6, after Alembic creates the PostgreSQL schema.

### Task 3: Execution and decision models

**Files:**
- Create: `infrastructure/database/models/execution.py`
- Create: `tests/database/test_execution_models.py`

**Interfaces:**
- Produces `AgentRun`, `Decision`, and `ToolCall`.
- Decision JSON list fields use `MutableList`; tool input/output objects use `MutableDict`.

- [ ] Write failing ORM contract tests for runs, decisions, tool calls, relationships, constraints,
  indexes, and PostgreSQL column types.
- [ ] Implement typed models with `NUMERIC(5,4)` confidence, JSONB mutation tracking, approved
  statuses, historical foreign keys, and indexes.
- [ ] Verify focused contract tests pass.
- [ ] Defer database-enforced confidence, iteration, and delete behavior to Task 6.

### Task 4: Historical score and audit models

**Files:**
- Create: `infrastructure/database/models/history.py`
- Create: `tests/database/test_history_models.py`

**Interfaces:**
- Produces `AppendOnlyMixin`, `AgentScore`, and `AuditEvent`.
- `AuditEvent.corrects_event_id` is a restricted self-reference.

- [ ] Write failing ORM contract tests for score/event fields, polymorphic actors, correlation IDs,
  correction links, constraints, indexes, and PostgreSQL column types.
- [ ] Implement both models with mutable-object JSONB fields, approved indexes, and restricted
  historical foreign keys.
- [ ] Verify focused contract tests pass.

### Task 5: Alembic and ephemeral PostgreSQL fixtures

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/20260825_0001_create_phase_2_core_schema.py`
- Create: `tests/database/conftest.py`
- Create: `tests/database/test_migrations.py`
- Modify: `core/config.py`
- Modify: `.env.example`
- Modify: `Dockerfile`
- Modify: `Makefile`

**Interfaces:**
- Alembic accepts a programmatic `sqlalchemy.url` override and imports `Base.metadata` plus models.
- Test fixtures expose migrated `database_url`, `connection`, and savepoint-isolated `db_session`.

- [ ] Add test-database connection settings using existing `POSTGRES_*` values with a host-only
  `TEST_POSTGRES_HOST=localhost`; never print credentials.
- [ ] Implement safe ephemeral-database helpers using `psycopg.sql.Identifier`, requiring the
  `synapseos_test_` prefix before drop.
- [ ] Start PostgreSQL with `docker compose up -d db` and verify it is healthy.
- [ ] Write a failing migration lifecycle test against a separate ephemeral database.
- [ ] Configure Alembic and create the reviewed initial migration with all nine tables, enums,
  constraints, indexes, and reversible downgrade.
- [ ] Update the Docker image to include Alembic files and add Makefile migration commands.
- [ ] Verify upgrade, downgrade, second upgrade, table set, and Alembic head all pass.
- [ ] Implement outer-transaction plus `join_transaction_mode="create_savepoint"` fixtures and add
  a test proving rows do not leak between tests.
- [ ] Write PostgreSQL integration tests for minimal create/read behavior and bidirectional
  relationships across all nine entities.
- [ ] Write PostgreSQL constraint tests for slug uniqueness, autonomy and score bounds, iteration
  bounds, duplicate/self dependencies, confidence bounds, and historical delete restrictions.
- [ ] Run those tests in RED against the migration, correct only the migration/models responsible,
  and verify GREEN.

### Task 6: Append-only guard and repositories

**Files:**
- Create: `infrastructure/database/append_only.py`
- Create: `infrastructure/database/repositories/__init__.py`
- Create: `infrastructure/database/repositories/agent_scores.py`
- Create: `infrastructure/database/repositories/audit_events.py`
- Modify: `infrastructure/database/session.py`
- Create: `tests/database/test_append_only.py`
- Create: `tests/database/test_repositories.py`

**Interfaces:**
- Produces `AppendOnlyViolationError` and idempotent `register_append_only_guard()`.
- Produces `AgentScoreRepository` and `AuditEventRepository` with `add`, `get_by_id`, and `list`.

- [ ] Write failing PostgreSQL tests proving insert/read work and direct update, indirect
  loaded-object update, mutable JSON update, and direct delete all fail.
- [ ] Implement the global `Session.before_flush` listener and register it from session setup.
- [ ] Verify append-only tests pass, including insertion of a correction event.
- [ ] Write failing PostgreSQL repository filter/order/pagination tests.
- [ ] Implement only add/get/list repository APIs; do not expose update/delete/merge/save.
- [ ] Verify repository tests and the complete suite pass.

### Task 7: Documentation, checklist, and full verification

**Files:**
- Modify: `README.md`
- Create: `docs/adr/0002-phase-2-data-model.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents migration commands, PostgreSQL test requirements, append-only scope, and Phase 2
  decisions.

- [ ] Update README and ADR in English without describing Phase 3 as implemented.
- [ ] Run the migration against the Docker development database from the API container.
- [ ] Run `.venv/bin/pytest` and require clean output with no skipped database tests.
- [ ] Run `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`.
- [ ] Run `.venv/bin/mypy .` in strict mode.
- [ ] Run `git diff --check` and inspect the complete diff for secrets and scope drift.
- [ ] Check only Phase 2 boxes whose work is proven by the preceding commands.
- [ ] Report created/modified files, commands, migrations, relations, tests, decisions, and any
  remaining issue. Do not commit or push unless explicitly requested.
