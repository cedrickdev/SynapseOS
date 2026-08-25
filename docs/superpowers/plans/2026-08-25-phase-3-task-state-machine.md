# Phase 3 Task State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize all persisted task-status changes in an audited, application-enforced state machine.

**Architecture:** A framework-independent `TaskStateMachine` owns the transition graph and appends an `AuditEvent` without committing. A global SQLAlchemy flush guard rejects status changes not authorized by the state machine, while a reviewed Alembic migration replaces the PostgreSQL enum and preserves existing rows.

**Tech Stack:** Python 3.12, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-25-phase-3-task-state-machine-design.md`

## Global Constraints

- Implement Phase 3 only; do not add LLM, agent, tool, event-bus, QA, security-engine, or API behavior.
- Keep code, comments, docstrings, migrations, and documentation in English.
- Use real PostgreSQL and Alembic for every persistence test; never use SQLite or `metadata.create_all()`.
- Every accepted transition requires actor and reason and creates an append-only audit event atomically.
- `COMPLETED` and `CANCELLED` are terminal; self-transitions are invalid.
- Do not commit or push unless explicitly authorized.

---

### Task 1: State vocabulary and transition graph

**Files:**
- Modify: `core/enums.py`
- Create: `core/tasks/state_machine.py`
- Test: `tests/tasks/test_task_state_machine.py`

**Interfaces:**
- Produces `ALLOWED_TASK_TRANSITIONS`, `InvalidTaskTransitionError`, `TaskTransitionValidationError`, and `TaskStateMachine.can_transition()`.

- [ ] Write an exhaustive failing test over every `TaskStatus` pair and the approved graph.
- [ ] Run the focused test and confirm RED because the state-machine module does not exist.
- [ ] Replace the task states and implement the immutable transition graph plus `can_transition`.
- [ ] Add validation tests for self-transition, terminal states, reason, and actor identity.
- [ ] Implement minimal explicit domain exceptions and input validation.
- [ ] Run focused tests and confirm GREEN.

### Task 2: Audited atomic transitions and direct-mutation protection

**Files:**
- Create: `infrastructure/database/task_status_guard.py`
- Modify: `infrastructure/database/session.py`
- Modify: `tests/database/conftest.py`
- Modify: `core/tasks/state_machine.py`
- Test: `tests/database/test_task_state_machine.py`

**Interfaces:**
- Produces `UnauthorizedTaskStatusChangeError`, idempotent `register_task_status_guard()`, and `TaskStateMachine.transition(...) -> AuditEvent`.

- [ ] Write failing PostgreSQL tests for successful persistence, audit payload, invalid-transition rollback, metadata copying, and direct assignment rejection.
- [ ] Register an idempotent global `before_flush` guard and cleanup listeners.
- [ ] Implement one-flush exact transition authorization and atomic audit insertion without commit.
- [ ] Verify direct status edits fail, non-status edits pass, and focused tests are GREEN.

### Task 3: PostgreSQL enum migration

**Files:**
- Create: `alembic/versions/20260825_0002_task_state_machine.py`
- Modify: `tests/database/test_migrations.py`

**Interfaces:**
- Migrates old rows to the 13-state enum and reverses them with documented lossy mappings.

- [ ] Extend migration tests with rows in `DRAFT`, `REJECTED`, `WAITING_HUMAN`, and `DONE`.
- [ ] Run the migration test and confirm RED at revision `0001`/new enum expectations.
- [ ] Implement explicit PostgreSQL enum replacement for upgrade and downgrade.
- [ ] Verify upgrade, downgrade, second upgrade, converted values, and Alembic head.

### Task 4: Documentation and final verification

**Files:**
- Create: `docs/task-state-machine.md`
- Create: `docs/adr/0003-phase-3-task-state-machine.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents the exact graph, audit contract, application-level guard, and Phase 3 boundaries.

- [ ] Add the Mermaid diagram and transition table in English.
- [ ] Record enum migration, human-waiting policy, atomic audit, and guard decisions in ADR-0003.
- [ ] Update repository status and only Phase 3 checklist boxes proven complete.
- [ ] Apply migrations from the Docker API container and run `alembic check`.
- [ ] Run complete pytest, Ruff lint, Ruff format check, and strict mypy.
- [ ] Run `git diff --check`, inspect scope and secrets, and confirm Phase 4 is untouched.
