# ADR-0010 — Transactional write tools

- **Status:** Accepted
- **Date:** 2026-08-27
- **Deciders:** SynapseOS maintainers

## Context

Developer Agents need to create and modify source files without gaining arbitrary host or shell
access. A filesystem mutation can succeed while output validation, cancellation, or mandatory
PostgreSQL audit finalization fails, so direct writes would produce unaudited or partially applied
state.

## Options considered

- Direct in-place writes — minimal code, but weak crash behavior and no reliable compensation.
- Permanent backup history — recoverable, but retains source and possible secrets indefinitely.
- Arbitrary unified-diff parsing — familiar interface, but a larger ambiguous parser and validation
  surface.
- Bounded exact replacements with temporary compensatable transactions — deterministic and small,
  while preserving immediate diffs for review.

## Decision

Use four explicit UTF-8 tools behind the existing permission and audit executor. Mutations require
the exact Phase 9 managed root, finite limits, non-following file validation, and a project-level
cross-process lock. Temporary backups and replacements live in a private manager area outside the
agent-visible workspace. The executor commits cleanup only after bounded output validation and
terminal audit flush; otherwise it restores the original state.

Use exact, ordered, unique text replacements for `patch_file`. Generate a bounded unified diff as
output, but do not accept arbitrary diff input. Make risk contribute to autonomy decisions and
classify deletion as `HIGH`.

## Consequences

- Writes are traceable and compensatable without permanent source retention.
- Project-level locking is deliberately conservative; independent files in one project do not
  mutate concurrently in this local backend.
- The filesystem and PostgreSQL do not share one atomic transaction. Fail-closed compensation and
  caller-owned DB rollback remain necessary when terminal audit persistence fails.
- Host administrators can still bypass application-level controls; stronger OS/container isolation
  belongs to a later backend phase.
- Shell execution, directory mutation, Git writes, and Phase 11 remain excluded.
