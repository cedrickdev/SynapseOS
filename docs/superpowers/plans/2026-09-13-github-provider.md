# Phase 41 GitHub Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, audited GitHub REST provider that can create branches and commits, manage pull requests, inspect reviews/checks, and merge only after the existing persisted merge gate passes.

**Architecture:** Keep local workspace Git unchanged and introduce a provider-neutral remote Git boundary. Implement GitHub through a reusable injected HTTP client, short-lived token providers, sanitized append-only auditing, and a fail-closed adapter to `SQLAlchemyMergeGate`.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, PyJWT with cryptography, SQLAlchemy 2, PostgreSQL, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-13-github-provider-design.md`

## Global Constraints

- Implement Phase 41 only; do not implement GitLab, webhooks, queues, workers, or Phase 42.
- Use English in code, comments, tests, branch names, and commit messages.
- Never persist, log, audit, or expose provider credentials.
- Require timeouts and bounded responses; perform no implicit retry.
- Propagate cancellation immediately and never close an injected HTTP client.
- Use TDD and real PostgreSQL with Alembic for database integration tests.
- Do not modify `README.md`; update only verified Phase 41 checklist items.

---

### Task 1: Provider-neutral remote contracts

**Files:**
- Create: `core/git_providers/__init__.py`
- Create: `core/git_providers/types.py`
- Create: `core/git_providers/ports.py`
- Create: `core/git_providers/errors.py`
- Test: `tests/git_providers/test_types.py`

**Interfaces:**
- Produces immutable bounded request/result models, `RemoteGitProvider`, `GitHubTokenProvider`,
  `RemoteGitAuditSink`, and `RemoteMergeGate` protocols.

- [ ] Write tests for canonical repository coordinates, branches, SHAs, paths, payload limits,
  merge inputs, and sanitized errors.
- [ ] Run the focused tests and observe failures caused by missing contracts.
- [ ] Implement the minimum immutable models and protocols.
- [ ] Run the focused tests to green and refactor without changing behavior.

### Task 2: GitHub HTTP boundary and authentication

**Files:**
- Create: `infrastructure/git/github/__init__.py`
- Create: `infrastructure/git/github/auth.py`
- Create: `infrastructure/git/github/http.py`
- Test: `tests/git_providers/test_github_auth.py`
- Test: `tests/git_providers/test_github_http.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `GitHubTokenProvider` and validated remote contracts.
- Produces: service-token and GitHub App installation-token suppliers plus a bounded JSON client.

- [ ] Write tests proving secret-free requests/errors, one App-token exchange, bounded responses,
  mandatory timeouts, no redirects/retries, cancellation propagation, and injected-client ownership.
- [ ] Run the focused tests and observe the expected missing implementation failures.
- [ ] Add the minimal JWT dependency and implement the authentication and HTTP boundaries.
- [ ] Run the focused tests to green and refactor.

### Task 3: Repository, branch, commit, and pull-request operations

**Files:**
- Create: `infrastructure/git/github/provider.py`
- Test: `tests/git_providers/test_github_provider.py`

**Interfaces:**
- Consumes: bounded GitHub JSON client and token supplier.
- Produces: `GitHubProvider` implementation for metadata, branch, commit/push, PR create/read,
  reviews, and checks.

- [ ] Write one failing behavior test per operation, including exact endpoint, expected SHA,
  allowlisted output, size limits, protected-branch rejection, and zero duplicate mutation calls.
- [ ] Run each focused test to confirm RED for the missing behavior.
- [ ] Implement the minimum endpoint orchestration to make each test pass.
- [ ] Run the complete provider test module to green and refactor common request handling.

### Task 4: Audited fail-closed merge

**Files:**
- Create: `infrastructure/git/github/audit.py`
- Create: `infrastructure/git/github/merge_gate.py`
- Modify: `infrastructure/git/github/provider.py`
- Test: `tests/git_providers/test_github_merge.py`
- Test: `tests/database/test_github_provider_audit.py`

**Interfaces:**
- Consumes: `AuditLogService`, `SQLAlchemyMergeGate`, provider PR/check reads, and an exact head SHA.
- Produces: append-only operation audit and a merge operation that cannot bypass the internal gate.

- [ ] Write failing unit tests for blocked gates, stale heads, missing/failing checks, audit failures,
  sanitized provider failures, and one successful SHA-bound merge request.
- [ ] Write failing real-PostgreSQL tests for logical actor audit identity and append-only events.
- [ ] Implement the SQLAlchemy adapters and audited merge orchestration.
- [ ] Run focused unit and PostgreSQL tests to green.

### Task 5: Composition, acceptance, and delivery

**Files:**
- Create: `infrastructure/git/github/composition.py`
- Modify: `.env.example`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Produces explicit owned-client composition and verified Phase 41 completion state.

- [ ] Write failing composition tests for mutually exclusive GitHub App/service-token settings and
  explicit owned-client cleanup.
- [ ] Implement composition without exposing credentials or weak defaults.
- [ ] Run all Phase 41 tests, then the full backend test suite, Ruff, and mypy.
- [ ] Verify `README.md` is unchanged and Phase 42 files/checklist are untouched.
- [ ] Check only Phase 41 items proven complete; leave GitLab and webhooks marked deferred.
- [ ] Commit with Conventional Commits, push the feature branch, open a PR, verify it, merge it,
  and synchronize local `main`.

