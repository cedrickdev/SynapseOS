# ADR-0012 — Provider-neutral local Git workflow

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** SynapseOS maintainers

## Context

Developer, Reviewer, QA, and Security roles need a shared Git handoff that is deterministic,
bounded, auditable, and independent from a hosting provider. Existing workspace import and
read-only Git tools do not provide task-branch ownership, safe commits, pull-request preparation,
or merge-requirement validation. Adding GitHub or GitLab now would introduce credentials, network
effects, and Phase 20 persistence before the local workflow is proven.

## Options considered

- Extend individual agent tools directly — fewer files, but duplicates authorization and audit
  behavior and couples roles to Git process details.
- Start with a remote-provider API — closer to production hosting, but expands authority, network,
  secret, retry, and persistence scope too early.
- Add a provider-neutral application workflow with one bounded local adapter — creates a stable
  contract while keeping all Phase 19 effects local and testable.

## Decision

Create `core/git_workflow` for immutable contracts, authority validation, deterministic merge
rules, audit orchestration, and provider ports. Create `infrastructure/git` for fixed-command local
Git execution, obvious-secret commit policy, PostgreSQL audit recording, and trusted composition.

Use internally derived task branches and explicit-path commits only. Protect `main` and
`production` conceptually. Produce checksum-bound local pull-request metadata and a read-only,
fail-closed merge gate requiring independent Reviewer, QA, Security, and deterministic checks.
Serialize operations per workflow instance and audit every public operation with metadata-only
append-only events. Trusted composition persists each audit lifecycle event through an independent
short database transaction so `STARTED` is durable before a Git mutation runs.

## Consequences

- Phase 19 works against real local Git repositories and real Alembic-managed PostgreSQL without
  remote credentials or provider coupling.
- Fixed commands, finite output, timeouts, cancellation cleanup, secret rejection, and explicit
  path staging reduce side effects and data exposure.
- The process-local lock does not coordinate separate processes or hosts.
- Pull-request persistence, remote provider adapters, push/fetch/merge, distributed locking,
  hosting-provider branch protection, and database-level Git controls remain deferred.
