# ADR-0003 — Audited task state machine

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** Platform Owner

## Context

The Phase 2 model persisted task states but did not define valid transitions or prevent services
from assigning `Task.status` directly. Phase 3 must provide a deterministic workflow, preserve
human escalation, and make every accepted state change traceable.

The Phase 3 checklist introduces QA and security gates and renames three Phase 2 states. Existing
database rows must survive this vocabulary change.

## Decision

- Replace the Phase 2 task-status enum with the Phase 3 workflow and retain `WAITING_HUMAN` as a
  thirteenth state required by the Company Constitution.
- Migrate `DRAFT` to `BACKLOG`, `REJECTED` to `CHANGES_REQUESTED`, and `DONE` to `COMPLETED`.
- Define one explicit directed transition graph. `COMPLETED` and `CANCELLED` are terminal.
- Allow every non-terminal workflow state to escalate to `WAITING_HUMAN` or cancel. Human-waiting
  work resumes only through `READY` or terminates through `CANCELLED`.
- Require a non-empty reason and an actor identifier for every actor except `SYSTEM`.
- Stage the status change and append-only `AuditEvent` in one caller-owned SQLAlchemy transaction.
- Reject direct persisted status mutation with a global `Session.before_flush` guard.

## Consequences

- Workflow transitions are deterministic, exhaustively testable, and independently auditable.
- Rollback is atomic: neither status nor audit history survives alone.
- The PostgreSQL downgrade is necessarily lossy: QA/security waiting states become
  `WAITING_REVIEW`, and `FAILED` becomes `BLOCKED`.
- The mutation guard is application-level. Database triggers, RLS, and dedicated roles remain
  deferred.
- Phase 3 records workflow intent but does not implement QA, security, agents, tools, or LLMs.
