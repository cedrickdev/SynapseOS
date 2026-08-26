# ADR-0007 — Database-backed permission authority

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** SynapseOS owner and engineering agent

## Context

Tool execution needs a deny-by-default authority that remains valid across processes and cannot be
forged by caller-supplied runtime data. Decisions must be explainable, project-scoped, revocable,
expirable, auditable, and compatible with future human approval without implementing that workflow
in Phase 7.

## Options considered

- Runtime permission IDs in `AgentProfile` or `ToolExecutionContext` — simple but caller-controlled,
  stale, and unsuitable as execution authority.
- Role inheritance — convenient for administration but implicit, difficult to audit, and premature.
- PostgreSQL `AgentPermission` grants with explicit global or project scope — persistent,
  queryable, constrained, and transactionally auditable.

## Decision

PostgreSQL `AgentPermission` rows are the sole execution authority. A provider-neutral permission
engine validates canonical identifiers, delegates to an injected SQLAlchemy policy, and requires a
sanitized append-only audit before returning. The policy verifies coherent agent/run/task/project
scope, active grants, and autonomy. Only `ALLOW` authorizes execution; `DENY` and `ASK` do not.
Production deployment always returns `ASK` even with a grant and sufficient autonomy.

The caller owns the shared transaction and session. No adapter commits, rolls back, closes,
retries, caches, or performs network work.

## Consequences

- Runtime profiles can describe permissions but cannot grant authority.
- Grant changes take effect on the next evaluation without cache invalidation.
- Each attempted registered and declared tool call has separate permission and tool audit records.
- Phase 7 has no grant mutation API or approval continuation mechanism.
- Database-level update/delete restrictions, RLS, and triggers remain future defense-in-depth work.
