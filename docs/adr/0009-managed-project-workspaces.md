# ADR-0009 — Managed project workspaces

- **Status:** Accepted
- **Date:** 2026-08-27
- **Deciders:** SynapseOS maintainers

## Context

Future agents and tools need one stable project filesystem scope without gaining arbitrary host
access. Local imports and remote clones also need bounded execution, fail-closed auditing, and
cleanup that remains safe after partial failures.

## Options considered

- Adopt arbitrary repository directories directly — simple, but ownership and containment cannot be
  enforced and source repositories could be mutated.
- Start with Docker execution workspaces — stronger process isolation, but expands Phase 9 into the
  later execution-container scope.
- Use manager-owned local roots behind a backend-neutral contract — provides a testable isolation
  boundary now while preserving a future Docker backend.

## Decision

Use one immutable `Workspace` per project under a private deterministic root. Import repositories
through private staging, enforce exact local/remote allowlists and finite resource limits, promote
atomically, and clean through manager-owned trash. Reuse the Phase 6 path guard and read-only tools.
Run Git without a shell, prompts, hooks, submodules, inherited credentials, or retries. Audit every
terminal lifecycle result through the append-only PostgreSQL audit boundary and fail closed if a
success cannot be audited.

No workspace table is introduced: the final path is derived from `project_id`, while provenance is
returned by the lifecycle operation. The abstraction permits a later Docker backend without adding
execution containers in Phase 9.

## Consequences

- Local isolation is explicit and deterministic, but it is not an OS-level sandbox.
- Repository sources are disabled by default and require administrator allowlists.
- One host can coordinate lifecycle operations using atomic lock directories; distributed locking
  is deferred until a multi-host backend exists.
- Compensation has independent finite safety ceilings so an oversized failed import can be removed.
- PostgreSQL contains audit records, not repository content, URLs, paths, prompts, or Git output.
