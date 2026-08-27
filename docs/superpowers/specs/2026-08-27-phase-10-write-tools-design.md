# Phase 10 — Transactional Write Tools Design

- **Status:** Approved
- **Date:** 2026-08-27
- **Scope:** Phase 10 only

## Objective

Phase 10 permits an authorized Developer Agent to modify UTF-8 source files inside one validated
managed project workspace. It extends the existing Phase 6 tool registry, Phase 7 permission
authority, Phase 9 workspace boundary, and PostgreSQL audit pipeline without weakening their
deny-by-default behavior.

This phase introduces no shell runner, arbitrary command execution, directory mutation, Git write,
container execution backend, MCP integration, autonomous loop, or Phase 11 behavior.

## Invariants

- Every mutation is scoped to the exact canonical `workspace_root` in `ToolExecutionContext`.
- Absolute paths, traversal, symbolic links, hard-link aliases, special files, forged workspace
  roots, and replaced path components are rejected.
- All write tools require an active persisted `filesystem.write` permission.
- `delete_file` is `HIGH` risk and requires reinforced authorization through the existing
  autonomy decision path.
- Original state is backed up before the visible mutation.
- Mutations are atomic from the local filesystem perspective and are restored if execution or
  terminal audit persistence fails.
- Inputs, existing files, generated outputs, diffs, backups, and process memory are finite.
- File content, diffs, backup names, absolute paths, credentials, prompts, and responses are never
  persisted in `ToolCall`, `AuditEvent`, error messages, or audit metadata.
- Cancellation is propagated after bounded compensation; it is never converted into success or an
  ordinary failure.
- The implementation performs no implicit retry and no duplicate mutation attempt.

## Tool contracts

All inputs are strict, immutable Pydantic models with unknown fields rejected.

### `write_file`

Replaces the complete content of one existing regular UTF-8 file.

Input:

- `path`: non-empty relative workspace path;
- `content`: bounded UTF-8 text.

The tool fails if the target is missing, is not a direct regular file, is a link, exceeds the
existing-file limit, or changes identity between validation and mutation.

### `create_file`

Creates one new regular UTF-8 file exclusively.

Input:

- `path`: non-empty relative workspace path;
- `content`: bounded UTF-8 text.

The parent directory must already exist inside the workspace. The tool does not create parent
directories and fails if any object already occupies the target path.

### `patch_file`

Applies an ordered, bounded tuple of exact text replacements to one existing regular UTF-8 file.

Each replacement contains:

- `old_text`: non-empty bounded UTF-8 text;
- `new_text`: bounded UTF-8 text.

For each replacement, `old_text` must occur exactly once in the state produced by the preceding
replacement. Zero or multiple matches fail the whole request before mutation. Empty replacement
sets and no-op final content are rejected. Phase 10 deliberately avoids parsing arbitrary unified
diff input; exact replacement has a smaller, deterministic validation surface.

### `delete_file`

Deletes one existing direct regular file. It does not delete directories recursively or otherwise,
and it rejects links and special files. The original file remains in a private temporary backup
until the terminal audit succeeds, then the backup is removed.

## Authorization and risk

The default registry adds the four tools but grants no authority by registration alone. Every tool
declares `filesystem.write`; the PostgreSQL permission policy remains the source of authority.

`write_file`, `create_file`, and `patch_file` use `MEDIUM` risk. `delete_file` uses `HIGH` risk and
a minimum autonomy threshold that produces `ASK` when human approval is required. A denied or
approval-required invocation never reaches filesystem code and still receives the existing
sanitized terminal audit record.

The executor serializes mutations by canonical resource path. Independent files may be mutated
concurrently; operations targeting the same canonical file cannot overlap. The lock key contains
no file content and is not persisted.

## Filesystem transaction boundary

A focused infrastructure component owns local text-file transactions. Tools do not implement
ad-hoc writes themselves.

For replacement and patch operations it:

1. validates the workspace and target without following links;
2. opens and reads the original regular file within the byte limit;
3. computes and validates the complete new UTF-8 state in bounded memory;
4. computes bounded change metadata and a bounded unified diff;
5. creates a randomized private backup and replacement in the target filesystem;
6. flushes the replacement and atomically replaces the target after identity revalidation;
7. returns an in-process transaction handle to the executor;
8. commits by deleting private artifacts only after terminal audit persistence succeeds;
9. restores the original atomically if execution, cancellation, or audit persistence fails.

Creation uses exclusive filesystem creation and retains enough transaction state to remove the new
file if audit persistence fails. Deletion atomically moves the target to a private backup and only
removes it after audit success.

Temporary artifacts use mode `0600`, random names, and the same filesystem needed for atomic
replacement. They are never returned to the caller. Path components and target identity are
revalidated immediately before the visible mutation. A concurrent replacement or path-type change
fails closed.

Backup cleanup is bounded. Failure to restore is surfaced as a stable sanitized compensation
failure and must never be hidden by the original error. Permanent version history is not retained;
Git and future memory systems remain separate concerns.

## Limits and results

Phase 10 adds finite configuration for:

- maximum input content bytes;
- maximum existing file bytes;
- maximum patch operations;
- maximum text per patch operation;
- maximum returned diff bytes;
- maximum transactional cleanup work.

The strict settings reject non-positive, non-finite, or excessive values. Defaults are conservative
and apply before expensive copying or diff generation.

Successful results contain only bounded JSON fields:

- relative path;
- operation classification;
- byte counts before and after;
- added and removed line counts;
- SHA-256 content hashes before and after when applicable;
- a UTF-8-safe bounded unified diff;
- an explicit `diff_truncated` flag.

Hashes support traceability without persisting content. A deletion result may include a bounded
diff for the immediate caller but the persisted audit stores only operation, result, duration,
tool identity, project/task/run correlation, and safe counters/classifications already permitted by
the existing recorder.

## Errors and cancellation

Public failures use stable non-sensitive codes for invalid input, permission denial, approval
required, workspace violation, missing target, target conflict, unsupported file, size limit,
ambiguous patch, mutation failure, compensation failure, audit failure, timeout, and cancellation.

Errors never echo rejected paths, content, diffs, repository data, temporary names, or underlying
OS exception text. Deterministic validation failures happen before backup or mutation. After a
visible mutation, every failure path attempts one bounded restoration. Cancellation is shielded
only for that bounded restoration and audit finalization, then the original cancellation is
immediately re-raised.

## Audit integration

The existing central executor remains responsible for `ToolCall` and append-only `AuditEvent`
records. The write transaction cannot be finalized until the terminal audit record is successfully
flushed in the caller-owned SQLAlchemy session.

This requires an explicit transactional tool result/compensation hook between the executor and
write tools. Read-only tools keep the existing simple execution contract. Injected sessions and
recorders are never committed, rolled back, or closed by tools.

Audit persistence contains no raw request arguments or tool output. A successful audit failure is
fail-closed: the filesystem is restored and the invocation returns `AUDIT_FAILED` or a stronger
compensation failure if restoration itself cannot be proven.

## Tests

Implementation follows RED–GREEN–REFACTOR. Unit tests use real temporary filesystems; persistence
tests use only real PostgreSQL migrated through Alembic, never SQLite or `metadata.create_all()`.

Required coverage includes:

- authorized create, replace, exact patch, and delete;
- missing target and create conflict;
- denied permission and human-approval result without mutation;
- traversal, absolute paths, symlink/hard-link aliases, special files, forged roots, and replaced
  path components;
- oversized input, original file, patch set, replacement, and returned diff;
- ambiguous and missing patch matches with all-or-nothing behavior;
- backup-before-mutation and removal after successful audit;
- execution failure, audit failure, and cancellation with verified restoration;
- same-path serialization and independent-path concurrency;
- bounded UTF-8 diff and deterministic hashes/counters;
- absence of sensitive content in errors, `ToolCall`, and `AuditEvent`;
- no mutation retry or duplicate audit;
- regression coverage for all Phase 6–9 read-only tools, permissions, workspaces, and append-only
  protections.

## Documentation and completion

Phase 10 will add an ADR and write-tool operator documentation, update configuration examples,
README, AGENTS guidance, and only the Phase 10 checklist boxes whose behaviors are proven.

Phase 10 is complete only when all four tools execute through the central permission/audit
boundary, rollback is proven, the complete test suite passes against PostgreSQL, Ruff and mypy are
clean, the Docker API image builds and remains healthy, Alembic reports no unintended schema
change, and no Phase 11 shell runner exists.
