# Phase 41 GitHub Provider Design

## Scope

Phase 41 connects the existing local Git and pull-request workflow to GitHub. It adds only a
GitHub implementation; GitLab, webhooks, queues, workers, and Phase 42 behavior remain deferred.

## Architecture

The existing `core.git_workflow.GitProvider` remains the local workspace boundary. Remote hosting
operations use a separate provider-neutral contract under `core.git_providers` so filesystem Git
and GitHub REST semantics do not leak into each other.

`infrastructure.git.github.GitHubProvider` implements the remote contract with one reusable,
injected `httpx.AsyncClient`. It never owns or closes an injected client. A separate composition
helper may create an owned client and exposes an explicit async lifecycle.

Authentication is supplied through a token-provider protocol. A GitHub App installation-token
provider is preferred and exchanges a short-lived signed app JWT for a one-hour installation
token. A backend service-token provider is supported for controlled local operation. Tokens are
held in memory only and never logged, audited, persisted, or returned in errors.

## Operations

The remote provider supports:

- bounded repository metadata;
- branch creation from an exact base SHA;
- bounded commit and push using GitHub's Git database API;
- pull-request creation and readback;
- review status and status/check-run summaries;
- merge only after the existing persisted `SQLAlchemyMergeGate` returns `PASS`.

Merge fails closed. The provider re-reads the pull request, requires its current head SHA to equal
the approved internal head SHA, evaluates the internal gate, re-reads remote checks, and sends the
same expected SHA in the merge request. Any stale, missing, truncated, or non-passing evidence
blocks the merge.

## Safety and bounds

- Every operation has a mandatory caller-supplied timeout.
- Responses are streamed and rejected above a fixed byte limit.
- No implicit retries, redirects, or duplicate mutation calls.
- Cancellation propagates without conversion or retry.
- Owner, repository, branch, SHA, path, text, collection, and payload sizes are validated.
- Only allowlisted GitHub response fields enter domain models or audit metadata.
- Provider errors contain stable codes and sanitized messages, never response bodies or secrets.
- Branch writes reject protected branches and non-fast-forward assumptions.
- Connection reuse and network ownership are explicit.

## Audit

Every remote action records append-only start and terminal events with logical actor, project,
task, agent run, correlation, repository, operation, and sanitized outcome. External mutations are
never reported as successful when terminal audit recording fails. Audit metadata remains shallow,
bounded, and allowlisted.

## Testing

Unit and contract tests use `httpx.MockTransport` and prove exact requests, response bounds,
timeouts, cancellation, no retries, sanitization, client ownership, authentication, and merge
fail-closed behavior. PostgreSQL integration tests use the real database and Alembic schema to
prove audit persistence and `SQLAlchemyMergeGate` enforcement. CI performs no live GitHub
mutation.

