# Transactional write tools

Phase 10 adds four bounded UTF-8 file mutation tools to the central SynapseOS tool boundary:
`write_file`, `create_file`, `patch_file`, and `delete_file`.

## Contracts

- `write_file` replaces one existing regular UTF-8 file.
- `create_file` exclusively creates one file below an existing workspace directory.
- `patch_file` applies an ordered tuple of exact replacements. Every old value must match exactly
  once in the preceding text state.
- `delete_file` removes one regular file. It never removes directories recursively or otherwise.

Absolute paths, traversal, symbolic links, hard-linked files, special files, missing parents,
forged workspace roots, oversized content, ambiguous patches, and changed targets fail closed.
Arbitrary unified-diff input is intentionally unsupported.

## Authorization

Registration never grants execution authority. All four tools require an active persisted
`filesystem.write` grant in the exact project scope. Create, write, and patch are `MEDIUM` risk;
delete is `HIGH` risk.

Risk now contributes to the autonomy gate:

| Risk | Minimum autonomy |
| --- | ---: |
| `LOW` | 0 |
| `MEDIUM` | 1 |
| `HIGH` | 2 |
| `CRITICAL` | Human approval always required |

Permission-specific rules remain cumulative and can impose a stronger decision. A denied or `ASK`
decision never reaches the filesystem.

## Transaction lifecycle

The local mutator validates the exact Phase 9 project root and acquires the existing cross-process
project lock. It computes the complete bounded change in memory, then creates private artifacts in
the workspace manager's `.transactions` area, outside the root visible to agents.

Replacement uses a flushed temporary file and atomic `os.replace`. Creation uses an exclusive hard
link from the private same-filesystem artifact. Deletion retains a private backup. The executor
validates the bounded result and flushes the terminal PostgreSQL audit before committing cleanup.
Output validation failure, audit failure, or cancellation restores the original state first.

No implicit retry occurs. A concurrent lifecycle or write operation for the project receives a
stable failure and may be retried only by an explicit higher-level policy. Locks are released even
when artifact cleanup fails.

## Results and audit

The immediate caller receives relative path, operation, before/after byte counts and SHA-256 hashes,
added/removed line counts, a UTF-8-safe bounded unified diff, and `diff_truncated`.

Persisted `ToolCall` and append-only `AuditEvent` records contain only bounded counters,
classifications, identities, scope, duration, and terminal status. They never contain file content,
diffs, absolute paths, temporary names, OS errors, credentials, prompts, or responses.

## Configuration

| Variable | Default | Maximum |
| --- | ---: | ---: |
| `WRITE_MAX_INPUT_BYTES` | 1 MiB | 16 MiB |
| `WRITE_MAX_EXISTING_BYTES` | 4 MiB | 16 MiB |
| `WRITE_MAX_PATCH_OPERATIONS` | 128 | 1,024 |
| `WRITE_MAX_PATCH_TEXT_BYTES` | 256 KiB | 1 MiB |
| `WRITE_MAX_DIFF_BYTES` | 256 KiB | 1 MiB |
| `WRITE_TIMEOUT_SECONDS` | 10 | 60 |

All values must be finite and positive. The immutable default registry requires an explicitly
configured `LocalTextMutator`; construction cannot silently omit or misconfigure Phase 10 tools.

## Scope boundary

This is application-level local filesystem protection, reinforced by private manager roots and
atomic filesystem operations. Phase 10 adds no shell runner, command parser, Git write, directory
mutation tool, execution container, MCP capability, autonomous retry loop, or Phase 11 behavior.
