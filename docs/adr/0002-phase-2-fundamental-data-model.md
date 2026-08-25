# ADR-0002 — Phase 2 fundamental data model

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** Platform Owner

## Context

Phase 2 requires the minimum persistence model needed by later runtime phases while explicitly
excluding task-transition behavior, autonomous execution, LLM integrations, reputation
aggregation, advanced auditing, and HTTP CRUD APIs.

The model must preserve traceability, distinguish decision confidence from historical agent
scores, and make accidental modification of score and audit history difficult. Database tests
must exercise the same PostgreSQL features used in production.

## Decision

- Use typed SQLAlchemy 2 models directly; do not introduce separate domain entities and ORM
  mappings until domain behavior justifies that complexity.
- Group the nine models by coherent domain: organization, work, execution, and history.
- Use application-generated UUIDs, UTC `TIMESTAMPTZ`, explicit PostgreSQL enums, JSONB, and
  `NUMERIC(5,4)` score/confidence values with database checks.
- Use `ON DELETE RESTRICT` for historical references. Only structural `TaskDependency` edges use
  `ON DELETE CASCADE`.
- Treat `AgentScore` and `AuditEvent` as append-only history. Their repositories expose only add,
  get, and deterministic list operations.
- Enforce append-only behavior globally with a SQLAlchemy `Session.before_flush` listener that
  rejects persisted dirty or deleted historical entities, including mutable JSON changes.
- Build every database test schema through Alembic on an ephemeral real PostgreSQL database. Do
  not use SQLite or `metadata.create_all()`.
- Publish Docker PostgreSQL on host port `55432` by default to avoid conflicts with a native local
  PostgreSQL commonly using `5432`; Docker-internal connections remain on `5432`.

## Consequences

- The schema is reproducible and its complete upgrade/downgrade lifecycle is tested.
- `AgentScore` stores measurement history rather than a calculated current reputation. Decision
  confidence remains on `Decision`.
- Audit corrections are new `AuditEvent` rows linked through `corrects_event_id`; original rows
  are never rewritten.
- Append-only protection is an application-level guarantee. PostgreSQL roles, triggers, RLS, and
  dedicated permissions are deferred to a later phase.
- Phase 3 remains responsible for task state-transition rules; the Phase 2 enums represent states
  without implementing transitions.
