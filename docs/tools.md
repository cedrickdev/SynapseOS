# Tool registry

Phase 6 provides a small, deny-by-default execution boundary for five read-only repository tools:

| Tool | Permission | Timeout | Main output limit |
|---|---|---:|---:|
| `read_file` | `filesystem.read` | 5 s | 256 KiB |
| `list_files` | `filesystem.read` | 5 s | 512 KiB |
| `search_text` | `filesystem.read` | 10 s | 512 KiB |
| `git_status` | `git.read` | 10 s | 256 KiB |
| `git_diff` | `git.read` | 10 s | 512 KiB |

The immutable default registry is created explicitly with `create_default_tool_registry()`. It has
no runtime registration or removal API. A caller must invoke tools through `ToolExecutor`; calling
a concrete tool directly bypasses the mandatory declaration, permission, timeout, output
validation, and audit lifecycle and is not an approved application path.

## Composition

```python
registry = create_default_tool_registry()
permission_engine = PermissionEngine(
    SQLAlchemyPermissionPolicy(caller_owned_session),
    SQLAlchemyPermissionAuditRecorder(caller_owned_session),
)
executor = ToolExecutor(
    registry,
    SQLAlchemyToolAuditRecorder(caller_owned_session),
    permission_engine,
)

result = await executor.execute(
    "read_file",
    {"path": "README.md"},
    execution_context,
)
```

The execution context identifies an existing agent run and contains a canonical workspace root and
the agent's declared tool IDs. It carries no permission authority. The executor resolves current
PostgreSQL grants through the Phase 7 Permission Engine, performs exactly one attempt, and never
retries or falls back. Cancellation is audited and immediately re-raised.

The SQLAlchemy recorder flushes a new `ToolCall` to obtain its ID, appends one terminal
`AuditEvent`, and flushes that terminal state before returning. It never commits, rolls back, or
closes the injected session. The caller therefore controls transaction atomicity and resource
lifetime.

## Filesystem boundary

- Paths must be non-empty, relative workspace paths without `..` or NUL characters.
- The workspace root must already exist and be canonical.
- Every path component is inspected without following links. All symlinks, including links whose
  targets remain inside the workspace, are rejected.
- Files must be regular UTF-8 files. `read_file` and search candidates are at most 8 MiB.
- `read_file` returns at most 256 KiB and supports bounded line ranges.
- `list_files` scans at most 10,000 entries and returns at most 512 KiB. It may report a symlink as
  an entry but never follows it.
- `search_text` is literal, not regular-expression search. It inspects bounded lines, returns at
  most 1,000 matches, and emits at most 512 KiB.
- File descriptors use no-follow semantics where the operating system provides them, reducing the
  validation/open race surface.

Truncation is explicit in structured output. No result can exceed the global 1 MiB `ToolResult`
limit.

## Git boundary

Git tools invoke the fixed `/usr/bin/git` executable without a shell and with a clean, fixed
environment. User input can only select validated relative path filters and an enum-defined diff
target. Commands disable color, text conversion, and external diff helpers. Standard output and
standard error are drained concurrently under hard byte limits so a subprocess cannot deadlock on
a full pipe. Timeout or cancellation terminates the process group and waits for cleanup.

`git_status` uses porcelain output. `git_diff` supports only the predefined worktree, staged, and
HEAD targets. These tools cannot commit, stage, reset, checkout, invoke hooks, or execute arbitrary
commands.

## Audit and data minimization

Audit begins before registry lookup, so unknown and denied attempts are recorded. A valid database
scope must link the supplied agent slug, agent run, task, and project. Forged or inconsistent scope
is rejected before a `ToolCall` is created.

Persisted input contains only `argument_count`. Terminal metadata is restricted to duration,
truncation, output field count, output byte count, and an optional stable error code. Audit storage
never receives argument names or values, file contents, search matches, Git diffs, subprocess
streams, absolute host paths, prompts, provider responses, environment values, or exception text.

Public results use stable statuses (`SUCCEEDED`, `FAILED`, `DENIED`, `TIMED_OUT`) and safe error
codes. Propagated cancellation is represented as `CANCELLED` in the append-only audit event and as
a failed tool-call record with the safe `CANCELLED` code.

## Permission boundary

Phase 7 checks persisted grant scope, activity, and autonomy before execution. Only `ALLOW`
executes; `DENY` and `ASK` return stable terminal errors. See [Permission engine](permissions.md)
for the policy and audit contract. Write tools, free-form shell execution, MCP, skill loading,
agent loops, retries, approval continuation, and dynamic discovery remain excluded.
