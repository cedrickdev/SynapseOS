# Phase 2 Fundamental Data Model Design

## Status

Approved in conversation on 2026-08-25. This document defines Phase 2 only.

## Objective

Create the typed SQLAlchemy 2 persistence model required by the SynapseOS runtime, backed and
tested exclusively by PostgreSQL. The phase delivers nine entities, explicit enums, integrity
constraints, Alembic migrations, append-only protections for historical records, and automated
integration tests.

## Scope

Phase 2 includes:

- `Agent`
- `Project`
- `Task`
- `TaskDependency`
- `AgentRun`
- `Decision`
- `ToolCall`
- `AgentScore`
- `AuditEvent`
- Alembic configuration and an initial migration
- append-only repositories and an application-level SQLAlchemy guard
- PostgreSQL integration and migration tests

Phase 2 excludes:

- task transition logic or a state machine
- LLM providers or LLM calls
- autonomous agent execution
- tool registration or permission enforcement
- reputation calculation or score aggregation
- advanced audit processing
- PostgreSQL triggers, row-level security, or dedicated database roles
- complete CRUD HTTP endpoints
- SQLite or `metadata.create_all()` in tests

## Architecture

The design uses SQLAlchemy models directly. It does not introduce separate domain entities and ORM
mappings before domain behavior justifies that complexity.

```text
core/enums.py
      |
      v
infrastructure/database/base.py
      |
      v
infrastructure/database/models/*
      |                    |
      v                    v
append-only guard      Alembic metadata
      |
      v
append-only repositories
      |
      v
PostgreSQL integration tests
```

`core/enums.py` contains only enums shared by the domain. Models are grouped by coherent domain,
not mechanically split one table per file. `base.py` contains only ORM primitives: declarative
base, metadata naming conventions, UUID primary-key support, and UTC timestamp support. Alembic
depends on model metadata, never on repositories.

## Common Persistence Rules

- Primary keys are application-generated UUIDs.
- Timestamps use PostgreSQL `TIMESTAMPTZ` and UTC server defaults.
- Mutable JSON objects use `MutableDict.as_mutable(JSONB)`.
- Mutable JSON lists use `MutableList.as_mutable(JSONB)`.
- Scores and confidence values use `NUMERIC(5,4)` with checks from `0` through `1`.
- Historical foreign keys use `ON DELETE RESTRICT`.
- Cascades are allowed only for structural `TaskDependency` rows.
- Index and constraint names use a deterministic SQLAlchemy metadata naming convention.

## Shared Enums

- `AgentSeniority`: `TRAINEE`, `JUNIOR`, `ENGINEER`, `SENIOR`, `STAFF`, `PRINCIPAL`
- `AgentStatus`: `AVAILABLE`, `ASSIGNED`, `WORKING`, `WAITING`, `BLOCKED`, `OFFLINE`
- `ProjectStatus`: `INTAKE`, `DISCOVERY`, `PLANNING`, `APPROVED`, `IN_PROGRESS`, `STAGING`,
  `CLIENT_REVIEW`, `COMPLETED`, `ARCHIVED`, `PAUSED`, `CANCELLED`
- `TaskStatus`: `DRAFT`, `READY`, `ASSIGNED`, `IN_PROGRESS`, `WAITING_REVIEW`, `REJECTED`,
  `BLOCKED`, `WAITING_HUMAN`, `DONE`, `CANCELLED`
- `TaskPriority`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
- `AgentRunStatus`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `TIMED_OUT`
- `DecisionOutcome`: `PENDING`, `ACCEPTED`, `REJECTED`, `SUPERSEDED`
- `ToolCallStatus`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `DENIED`, `TIMED_OUT`
- `AgentScoreType`: `CONFIDENCE`, `RELIABILITY`, `EXPERTISE`, `CODE_QUALITY`, `SECURITY`,
  `COLLABORATION`, `CUSTOMER_SATISFACTION`
- `ScoreSourceType`: `REVIEW`, `QA`, `SECURITY`, `FEEDBACK`, `SYSTEM`
- `AuditActorType`: `AGENT`, `HUMAN`, `SYSTEM`, `WORKER`, `TOOL`, `WEBHOOK`
- `AuditResult`: `SUCCEEDED`, `FAILED`, `DENIED`, `CANCELLED`

Enums persist valid values only. Phase 3 will define task transition rules; Phase 2 must not do so.

## Entity Design

### Agent

Fields: `id`, `name`, unique indexed `slug`, `role`, `department`, `seniority`, `status`,
`autonomy_level`, `reputation_score`, `reliability_score`, `created_at`, and `updated_at`.

Constraints:

- `0 <= autonomy_level <= 5`
- `0 <= reputation_score <= 1`
- `0 <= reliability_score <= 1`

The two score fields are current materialized values. Historical `AgentScore` rows remain the source
from which a later reputation engine can calculate them.

### Project

Fields: `id`, `name`, nullable `description`, `status`, nullable `client_name`, `created_at`, and
`updated_at`. Status defaults to `INTAKE`.

### Task

Fields: `id`, required `project_id`, nullable self-referencing `parent_task_id`, `title`, nullable
`description`, `status`, `priority`, nullable `assigned_agent_id`, `acceptance_criteria`,
`max_iterations`, `iteration_count`, `created_at`, and `updated_at`.

`acceptance_criteria` is a mutable JSON list. Constraints require `max_iterations >= 1`,
`iteration_count >= 0`, and `iteration_count <= max_iterations`.

Indexes cover `(project_id, status)`, `(assigned_agent_id, status)`, and `parent_task_id`.

### TaskDependency

Fields: `id`, required `task_id`, required `depends_on_task_id`, and `created_at`.

Constraints:

- unique `(task_id, depends_on_task_id)`
- `task_id != depends_on_task_id`

Both foreign keys use structural `ON DELETE CASCADE`. This cascade deletes only dependency edges;
historical rows referencing a task continue to restrict deletion. Graph cycle detection belongs to
later runtime logic.

### AgentRun

Fields: `id`, required `agent_id`, required `task_id`, `status`, nullable `started_at`, nullable
`finished_at`, `iteration`, nullable `confidence`, nullable `error_message`, and `created_at`.

Constraints require `iteration >= 1` and, when present, `0 <= confidence <= 1`. Indexes cover
agent/status, task/status, and creation time.

### Decision

Fields: `id`, `decision`, mutable-list `alternatives`, `justification`, nullable `confidence`,
mutable-list `evidence`, required `agent_id`, required `task_id`, `outcome`, nullable
`final_result`, `created_at`, and `updated_at`.

Confidence describes this decision only and remains separate from `AgentScore`. It is constrained
to `0..1`. Indexes cover agent, task, outcome, and creation time.

### ToolCall

Fields: `id`, required `agent_run_id`, `tool_name`, `action`, mutable-object `input_data`,
mutable-object `output_data`, `status`, nullable `started_at`, nullable `finished_at`, nullable
`error_message`, and `created_at`.

Indexes cover run/status, tool name, and creation time. Duration, token accounting, and cost
tracking are deferred.

### AgentScore

Fields: `id`, required `agent_id`, nullable `project_id`, nullable `task_id`, `score_type`, `value`,
`justification`, `source_type`, nullable textual `source_id`, mutable-object `metadata`, and
`created_at`.

`AgentScore` is an immutable measurement event, not the current agent score. `value` is constrained
to `0..1`. Indexes cover individual foreign keys and `(agent_id, score_type, created_at)`.

### AuditEvent

Fields: `id`, nullable `actor_type`, nullable textual `actor_id`, nullable `project_id`, nullable
`task_id`, nullable `agent_run_id`, `event_type`, `action`, nullable `resource_type`, nullable
textual `resource_id`, `result`, mutable-object `data`, nullable UUID `correlation_id`, nullable
self-referencing `corrects_event_id`, and `created_at`.

`actor_id` is deliberately polymorphic and has no foreign key. A correction is represented by a
new event whose `corrects_event_id` references the original; the original is never updated.

Indexes cover chronological reads, project/time, task/time, run/time, event type/time,
correlation ID, and correction target.

## Relationships and Delete Policy

The ORM exposes bidirectional relationships for the entity graph. Historical relationships use
`ON DELETE RESTRICT`: agents, projects, tasks, and runs cannot be deleted while runs, decisions,
scores, tool calls, or audit events refer to them. ORM relationships must not use `delete-orphan`
for historical records.

`TaskDependency` is the only structural cascade. Removing a deletable task removes dependency
edges attached to it but never removes history.

## Append-Only Enforcement

`AgentScore` and `AuditEvent` implement an `AppendOnlyMixin`. Their repositories expose only:

- insert (`add`)
- lookup by identifier (`get_by_id`)
- deterministic filtered reads (`list`)

They expose no update, merge, save, or delete operations.

An idempotently registered global `Session.before_flush` listener inspects `session.dirty` and
`session.deleted`. Any persisted `AgentScore` or `AuditEvent` in either collection causes an
explicit `AppendOnlyViolationError`. New objects in `session.new` are allowed. Mutable JSON
tracking ensures in-place changes are also detected.

This is an application-level guarantee. PostgreSQL roles, permissions, RLS, policies, and triggers
are explicitly deferred.

## Alembic Design

`alembic/env.py` imports model metadata directly, reads the configured database URL, accepts a test
URL override, enables type comparison, and executes migrations transactionally. The initial
migration creates PostgreSQL enums, tables, foreign keys, checks, unique constraints, and indexes.
Its downgrade removes tables in dependency order, then removes enums.

The checked-in migration is reviewed as source code. Tests do not call `metadata.create_all()`.

## PostgreSQL Test Isolation

Tests use the real Docker PostgreSQL server exclusively. A session-scoped fixture connects to the
administrative `postgres` database, creates a uniquely named `synapseos_test_<uuid>` database,
runs `alembic upgrade head`, and drops only that database at teardown.

Safety requirements:

- database deletion is refused unless the name starts with `synapseos_test_`;
- SQL identifiers use `psycopg.sql.Identifier`, not interpolation;
- unavailable PostgreSQL produces an explicit failure, never an SQLite fallback or silent skip;
- all pooled connections are disposed before database deletion.

Each test runs inside an outer connection transaction. Its SQLAlchemy session uses
`join_transaction_mode="create_savepoint"`, allowing repository code to call `commit()` or
`rollback()` without escaping isolation. Teardown closes the session and rolls back the outer
transaction, restoring the migrated database to a clean state.

Migration lifecycle testing uses a second ephemeral database so downgrade cannot disturb regular
integration tests. It verifies `upgrade head`, all nine tables and the current Alembic revision,
`downgrade base`, table removal, and a second `upgrade head`.

## Test Coverage

Tests must prove:

- minimal create/read behavior for all nine entities;
- bidirectional SQLAlchemy relationships;
- enum persistence;
- agent slug uniqueness;
- autonomy, score, confidence, and iteration bounds;
- duplicate and self task dependencies are rejected;
- historical deletes are rejected;
- dependency-edge cascade is structural only;
- append-only inserts and reads succeed;
- direct updates and deletes fail;
- indirect loaded-object and in-place JSON mutations fail;
- corrective audit-event insertion succeeds;
- repository filters, ordering, and pagination work;
- Alembic upgrade/downgrade/upgrade succeeds;
- database state does not leak between tests.

## Acceptance Criteria

Phase 2 is complete only when:

- Alembic migrations run successfully against PostgreSQL;
- SQLAlchemy relationships and database constraints are tested;
- all persisted states use explicit enums;
- minimal CRUD and append-only behavior are tested;
- pytest, Ruff, formatting, and strict mypy checks pass;
- the Phase 2 checklist is updated only for verified items;
- no Phase 3 behavior has been introduced.
