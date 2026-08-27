# Phase 9 — Workspace and Isolation Design

- **Status:** Approved
- **Date:** 2026-08-27
- **Scope:** Phase 9 only

## 1. Objective

Phase 9 gives each persisted project one controlled local workspace. It introduces workspace
lifecycle management without adding write tools, a general shell runner, execution containers,
MCP, autonomous loops, or any Phase 10 behavior.

The workspace boundary must ensure that future agent tools can operate only inside the project root,
that local repositories are imported rather than adopted in place, and that every lifecycle attempt
is represented by a sanitized append-only audit event.

## 2. Non-goals

Phase 9 does not provide:

- agent-facing file mutation tools;
- arbitrary command or shell execution;
- Docker execution backends or container orchestration;
- workspace persistence APIs or a workspace database table;
- remote credentials, credential storage, interactive Git authentication, or retries;
- branch, commit, push, pull-request, test-runner, or build behavior;
- workspace sharing across projects or tenants.

## 3. Design principles

- **Managed roots only:** a workspace always lives below one configured SynapseOS base directory.
- **Import, never adopt:** an existing repository is copied through Git into the managed root and is
  never used directly as an agent workspace.
- **One project, one root:** the final path is deterministically derived from the project UUID.
- **Immutable runtime scope:** a returned `Workspace` is a strict frozen value object whose root
  cannot be replaced.
- **Deny by default:** malformed identifiers, unsafe roots, unapproved sources, unsafe URLs,
  links at trust boundaries, limit violations, collisions, and inconsistent state are rejected.
- **Atomic visibility:** incomplete work remains in private staging and is promoted atomically only
  after validation.
- **Bounded resources:** Git duration, output, filesystem entries, total bytes, and traversal depth
  have finite fixed or configured limits.
- **Sanitized observability:** audits contain identifiers, stable result codes, finite counts, and
  durations, never raw paths, repository content, Git output, URL credentials, or environment data.

## 4. Components

### 4.1 Core contracts

`core/workspaces/types.py` defines strict immutable Pydantic models:

- `Workspace`
  - `project_id: UUID`
  - `root: Path`, already canonical and present
  - `provenance: WorkspaceProvenance`
- `WorkspaceProvenance`
  - `EMPTY`
  - `LOCAL_IMPORT`
  - `REMOTE_CLONE`
- bounded operation request/value types where a structured boundary is useful;
- stable public result/error codes that do not include rejected input.

`core/workspaces/manager.py` defines the provider-neutral asynchronous `WorkspaceManager`
protocol. Its operations are:

- `create_workspace(project_id, audit_context)`;
- `attach_existing_repository(project_id, source, audit_context)`;
- `clone_repository(project_id, repository_url, audit_context)`;
- `validate_path(workspace, relative_path, ...)`;
- `cleanup_workspace(project_id, audit_context)`.

The abstraction has no dependency on Git, SQLAlchemy, Docker, or host-specific process APIs.

### 4.2 Local infrastructure backend

`infrastructure/workspaces/local.py` implements `WorkspaceManager` for a single host. It receives:

- one canonical managed base root;
- an explicit finite allowlist of canonical local import roots;
- an explicit finite allowlist of remote HTTPS hostnames;
- bounded timeout and filesystem limits;
- a Git process adapter;
- an audit recorder.

Dependencies are injected. An injected client, process adapter, SQLAlchemy session, or transaction is
never closed, committed, or rolled back by the manager.

### 4.3 Git process boundary

`infrastructure/workspaces/git.py` owns the only Git subprocess calls used by Phase 9. It executes a
fixed Git binary directly with structured arguments and never invokes a shell.

For local import it uses Git clone semantics that copy objects rather than hardlinking or reusing the
source repository. For remote clone it accepts HTTPS URLs only. It rejects user information,
passwords, query strings, fragments, non-allowlisted hosts, local/file protocols, and ambiguous URL
forms before starting a process.

The process boundary enforces:

- one attempt, with no implicit retry;
- a mandatory timeout;
- bounded captured stdout and stderr that are never returned or audited verbatim;
- non-interactive operation and disabled credential helpers;
- immediate cancellation propagation followed by process termination and staging cleanup;
- no hooks or repository-provided executable code during clone.

## 5. Filesystem layout and lifecycle

The configured base contains only manager-owned directories:

```text
<workspace-base>/
├── .staging/
│   └── <project-uuid>-<random-token>/
├── .locks/
│   └── <project-uuid>/
├── .trash/
│   └── <project-uuid>-<random-token>/
└── projects/
    └── <project-uuid>/
```

All manager-owned roots are created with private permissions. The final project root is derived by
formatting a validated UUID; callers never supply a final path. A project operation first acquires
its lock with one atomic directory creation and always releases that exact lock in a `finally`
boundary.

Creation flow:

1. Validate exact request types and audit context.
2. Verify that the project exists through the audit/persistence boundary.
3. Atomically acquire the project lock and refuse an existing final root or active operation.
4. Create a unique private staging directory below `.staging`.
5. Create an empty workspace, import a local repository, or clone an approved remote repository.
6. Walk the staging tree without following links and enforce entry, byte, and depth limits.
7. Verify that all trust-boundary directories are real directories and canonically contained.
8. Atomically rename staging to the deterministic final path.
9. Append the terminal audit event and return an immutable canonical `Workspace`.

If a step before promotion fails, the final root never becomes visible. If successful-audit
recording fails after promotion, the manager immediately moves the root into manager-owned trash
and removes it before returning failure. The manager removes only exact staging/trash directories it
created and reports one stable sanitized failure. This compensating action prevents callers from
receiving an unaudited usable workspace; filesystem and PostgreSQL cannot provide one shared atomic
transaction.

## 6. Path containment

Phase 9 reuses and, where required, generalizes the Phase 6 path guard rather than creating a second
containment policy. `validate_path()` accepts only non-empty relative paths, rejects NUL bytes,
absolute paths and `..`, rejects link traversal, resolves canonical containment, and optionally
checks the expected resource kind.

The workspace root itself must be a canonical direct child of the configured projects directory and
must match `workspace.project_id`. A forged `Workspace`, a subclass instance, a replaced root, or a
root from another manager is rejected.

Repository symlinks may exist as inert Git data, but SynapseOS never follows them. Existing Phase 6
filesystem and Git tools continue to reject any operation that traverses a symlink component.

## 7. Local import policy

`attach_existing_repository()` accepts an existing local Git repository only when:

- the source is below one explicitly configured canonical import root;
- neither the allowlisted root, source root, nor trust-boundary path is a symlink;
- the source is a valid Git work tree;
- the source is outside the managed workspace base;
- Git imports it into fresh staging without hardlinks;
- the imported snapshot passes all workspace limits.

The source repository is read-only from the manager's perspective. The imported workspace contains
the committed Git snapshot; untracked source files are intentionally excluded. Tests must prove
that tracked and untracked source state, refs, configuration, and file timestamps are not
intentionally modified by the import operation.

## 8. Remote clone policy

Remote clone is disabled unless at least one hostname is configured. Accepted URLs must use HTTPS,
contain a non-empty allowlisted hostname and repository path, and contain no user information,
password, query, fragment, control character, or encoded ambiguity that could change Git's
interpretation.

The allowlist is exact-host matching after lowercase IDNA normalization. Redirect behavior is not
implemented by SynapseOS. Secrets are never accepted as URL components, command arguments, audit
metadata, or public errors. Authentication support requires a future separately designed credential
boundary.

## 9. Cleanup

`cleanup_workspace()` derives the target from a validated project UUID. Before removal it verifies
that the base, projects directory, and target are canonical manager-owned directories; the target
must be the exact expected direct child and must not be a link.

The target is atomically renamed to a unique manager-owned trash path before bounded recursive
deletion. Recursive deletion unlinks links as entries and never follows them. Cleanup refuses the
base root, `.staging`, `.locks`, `.trash`, `projects`, arbitrary caller paths, mismatched project
roots, and inconsistent filesystem state.

An absent workspace returns a stable not-found result and is audited; it is not silently treated as
successful cleanup.

## 10. Audit model

Every requested lifecycle operation produces one append-only terminal `AuditEvent` through an
injected recorder. Events use:

- `event_type = WORKSPACE_LIFECYCLE`;
- actions `create_workspace`, `attach_existing_repository`, `clone_repository`, or
  `cleanup_workspace`;
- `resource_type = WORKSPACE`;
- `resource_id = project_id`;
- the supplied actor, project, and correlation identifiers;
- terminal `SUCCEEDED`, `FAILED`, `DENIED`, or `CANCELLED` results.

Allowlisted data is limited to provenance, stable error code, duration, entry count, total byte
count, and cleanup status. Absolute paths, source paths, full URLs, host environment, Git output,
file names, file contents, credentials, and parser/process exceptions are excluded.

Audit failure is fail-closed: a workspace is not returned as usable when its successful lifecycle
event cannot be appended. The recorder flushes but never commits or owns the caller transaction.

## 11. Persistence decision

Phase 9 adds no workspace table or migration. The final root is deterministic from `project_id`, and
the existing append-only audit log records lifecycle history. This avoids introducing mutable
distributed workspace state before a multi-worker or Docker backend exists.

The local backend reconstructs a `Workspace` only after revalidating the deterministic root. A future
distributed backend may add explicit persistence through a separate ADR and migration.

## 12. Concurrency and failure behavior

Manager operations for one project are mutually exclusive. Atomic lock-directory creation and
filesystem rename primitives, not an in-memory lock alone, provide the cross-process collision
boundary. A final root collision or active lock fails deterministically; it never merges directory
contents. Locks carry no process details or sensitive metadata, and stale-lock recovery is not
automatic in Phase 9 because guessing process liveness could permit concurrent mutation.

Failures are represented by stable error codes such as invalid request, project unavailable,
workspace exists, workspace missing, unsafe path, source denied, remote denied, Git failed, timeout,
cancelled, resource limit, cleanup failed, and audit failed. Public messages contain no rejected
values. There are no fallbacks, retries, partial successes, or hidden failures.

## 13. Resource limits

The local backend requires finite positive configuration for:

- Git timeout;
- maximum captured process-output bytes;
- maximum workspace entries;
- maximum total regular-file bytes;
- maximum traversal depth;
- maximum configured local roots and remote hosts.

Filesystem accounting uses `lstat`/non-following traversal. Special files are rejected. Limits are
checked before final promotion and again when reconstructing an existing workspace where material.

## 14. Testing strategy

Implementation follows strict RED-GREEN-REFACTOR TDD. Tests cover:

- strict immutable contracts and forged-value rejection;
- deterministic isolated roots for distinct projects;
- atomic empty creation and collision handling;
- local import without adopting or modifying the source;
- local source allowlist enforcement and symlink-boundary rejection;
- bounded remote HTTPS clone with URL and hostname policy;
- fixed no-shell Git arguments, timeout, cancellation, and no retries;
- staging cleanup after every terminal failure;
- traversal, absolute path, NUL, link escape, and mismatched-root rejection;
- entry, byte, depth, and special-file limits;
- exact-target cleanup and refusal of parent/arbitrary paths;
- sanitized append-only audits for success, denial, failure, cancellation, and cleanup;
- no session commit/rollback/close ownership;
- compatibility with Phase 6 read-only filesystem and Git tools;
- real PostgreSQL tests using Alembic, never `metadata.create_all()`;
- full regression, Ruff, Ruff format, strict mypy, Docker, Alembic, and API health checks.

Tests use real temporary Git repositories and deterministic fake process adapters where timeout or
cancellation must be forced without network access. No test depends on an external Git provider.

## 15. Documentation and acceptance

Phase 9 updates:

- `docs/workspaces.md`;
- a workspace architecture ADR;
- `README.md` and `AGENTS.md` current-status boundaries;
- Phase 9 checkboxes only after corresponding behavior is verified.

Phase 9 is complete when every listed lifecycle operation is implemented through the local backend,
all containment/audit/resource guarantees have tests, the complete verification suite is green, and
no Phase 10 write tool or later-phase execution feature exists.
