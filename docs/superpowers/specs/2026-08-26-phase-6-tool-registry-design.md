# Phase 6 Tool Registry Design

**Date:** 2026-08-26  
**Status:** Approved in conversation  
**Scope:** Phase 6 only

## Objective

Phase 6 introduces an explicit registry of bounded read-only capabilities. An agent may invoke only
a registered tool that is declared on its profile and whose required permission identifiers are
present in the execution context. Every attempt passes through one executor that applies validation,
workspace containment, timeout, cancellation, output limits, and audit recording consistently.

This phase does not connect tools to the Phase 5 `Agent` methods. It creates the independently
testable boundary that a later orchestration phase can consume.

## Included scope

Phase 6 includes:

- typed tool definitions and results;
- a duplicate-safe `ToolRegistry`;
- a single `ToolExecutor` enforcement point;
- a typed `ToolExecutionContext`;
- deterministic Phase 6 checks for declared tools and permission membership;
- automatic `ToolCall` and `AuditEvent` persistence through an injected audit port;
- `read_file`, `list_files`, `search_text`, `git_status`, and `git_diff`;
- strict workspace containment, including symlink escape protection;
- bounded inputs, outputs, directory traversal, search results, subprocess output, and execution time;
- cancellation propagation and sanitized errors;
- unit tests plus real-PostgreSQL audit integration tests.

## Explicit exclusions

Phase 6 does not include:

- the Phase 7 Permission Engine or policy evaluation;
- runtime attachment to `Agent`;
- write, edit, delete, shell, network, MCP, or deployment tools;
- arbitrary commands, command strings, `shell=True`, or user-controlled environment variables;
- workspace creation or lifecycle management from Phase 9;
- dynamic plugin discovery, entry points, or automatic imports;
- retries, autonomous loops, background jobs, or concurrent tool scheduling;
- persistence of file contents, diffs, search matches, prompts, or raw tool responses;
- database triggers, RLS, or PostgreSQL permission hardening.

## Architecture

```text
Caller
  -> ToolExecutor
     -> validate ToolExecutionContext
     -> begin audit record
     -> ToolRegistry lookup
     -> declared-tool check
     -> required-permission membership check
     -> enforce timeout and propagate cancellation
     -> registered Tool.execute()
     -> validate and bound result
     -> finish ToolCall and append AuditEvent
  -> ToolResult
```

The registry discovers nothing. The application composition root constructs the five approved tools
and registers them explicitly. The executor is the only public invocation path documented for normal
application use.

## Module boundaries

```text
core/tools/
├── __init__.py       public Phase 6 API
├── types.py          strict immutable values and tool-specific risk/status enums
├── errors.py         sanitized domain errors
├── tool.py           generic asynchronous Tool contract
├── registry.py       explicit immutable registry
├── executor.py       shared enforcement and lifecycle
└── audit.py          persistence-neutral audit port and call handle

infrastructure/tools/
├── __init__.py       concrete tool exports and default registry factory
├── paths.py          canonical workspace/path containment primitives
├── filesystem.py     read_file, list_files, and search_text
├── git.py            fixed-argument git_status and git_diff adapters
└── audit.py          SQLAlchemy ToolCall/AuditEvent recorder
```

Core modules do not import SQLAlchemy or concrete infrastructure tools. Infrastructure implements the
core contracts and may import the Phase 2 ORM models.

## Core contracts

### Identifiers and enums

Tool names and permission identifiers use the existing lowercase identifier convention. Tool risk
is local to the tools domain and therefore does not extend `core/enums.py`.

```python
class ToolRiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMED_OUT = "TIMED_OUT"
```

All five Phase 6 tools are `LOW` risk because they are bounded and read-only. This classification does
not grant permission by itself.

### Tool execution context

`ToolExecutionContext` is a strict frozen Pydantic model containing:

- canonical `workspace_root` supplied by the caller;
- `agent_id`, `agent_run_id`, `project_id`, and `task_id`;
- `declared_tool_ids` copied from the agent profile;
- `permission_ids` already granted to the run;
- `correlation_id` for traceability.

The context requires non-empty bounded identifiers, UUID run/project/task/correlation values, a
present directory for `workspace_root`, and bounded immutable identifier sets. It contains no session,
repository, provider client, secret, prompt, or mutable policy engine.

The Phase 6 permission check is deliberately narrow:

```text
requested tool name in declared_tool_ids
AND
tool.required_permissions is a subset of permission_ids
```

No hierarchy, wildcard, role policy, approval flow, or autonomy calculation is introduced before
Phase 7.

### Tool definition

Each concrete tool implements a generic asynchronous contract with:

- `name`;
- `description`;
- `input_type`, a strict Pydantic model class;
- `required_permissions`, an immutable set;
- `risk_level`;
- `timeout_seconds`, positive and no greater than 30 seconds;
- `execute(arguments, context)`.

The executor reconstructs the input with `strict=True` and `extra="forbid"` before execution. The
input JSON schema is exposed through `input_type.model_json_schema()`; no second hand-written schema
may diverge from validation.

### Tool result

`ToolResult` is strict and frozen. It contains:

- tool name and result status;
- a bounded JSON-compatible output mapping;
- safe error code and safe error message when unsuccessful;
- duration in milliseconds;
- `truncated` flag;
- the persisted `tool_call_id`.

The complete serialized result is capped at 1 MiB, while concrete tools use lower limits. Error
messages never contain raw input, file content, command output, host paths, environment values, or
provider metadata. Cancellation raises `asyncio.CancelledError`; it is not converted into a normal
result.

### Registry

`ToolRegistry` is built from an iterable of tool instances. Construction validates every descriptor
and rejects duplicate names. It exposes only immutable lookup and listing operations. Registration or
replacement after construction is absent from Phase 6, preventing runtime mutation races and hidden
capability injection.

### Executor

`ToolExecutor` receives a registry and audit recorder through its constructor and does not own either
resource. For each invocation it:

1. validates the context and raw arguments without retaining them;
2. asks the audit recorder to create a `RUNNING` `ToolCall` using only the requested tool name and
   argument count; caller-controlled keys and values are not retained;
3. obtains the registered tool or returns an audited, sanitized unknown-tool failure without
   executing code;
4. denies undeclared tools;
5. denies missing required permission identifiers;
6. runs exactly one `execute()` call under the tool timeout;
7. validates and bounds the output;
8. updates `ToolCall` to its terminal state and appends one `AuditEvent`;
9. returns a structured result or propagates cancellation.

Malformed execution contexts that cannot establish actor/run scope fail before audit creation and
before any tool lookup or execution. All attempts with valid execution scope, including unknown,
undeclared, unauthorized, and invalid-input requests, receive terminal `ToolCall` and `AuditEvent`
records.

There are no implicit retries. Timeout produces `TIMED_OUT`; validation, tool, and audit failures are
distinguishable by safe error codes. A failure to create the initial audit record fails closed before
the tool runs. The executor never closes an injected audit recorder or database session.

## Audit contract

The persistence-neutral recorder exposes start and finish operations. Its SQLAlchemy adapter stages
changes in the injected session and flushes only when an identifier is required; it never commits,
rolls back, or closes the caller-owned session.

The initial `ToolCall` records:

- agent run identifier;
- tool name and fixed action name;
- `RUNNING` status and start time;
- sanitized input metadata only.

Terminal completion records status, finish time, duration/size/truncation metadata, and a safe error
code when applicable. It appends an `AuditEvent` with actor `AGENT`, project/task/run/correlation
scope, event type `TOOL_EXECUTION`, a fixed action, and a mapped audit result.

Persisted input/output metadata may contain relative path, requested limits, counts, byte sizes,
hashes, exit codes, and truncation flags. It must not contain file contents, diff contents, search
matches, raw subprocess streams, prompts, environment values, or absolute host paths.

`AuditEvent` remains append-only. `ToolCall` is the mutable lifecycle projection already approved by
the Phase 2 schema.

## Workspace and path security

Every filesystem request is relative to a mandatory canonical workspace root. Inputs reject absolute
paths, NUL bytes, blank paths, and parent traversal components. The path guard inspects every existing
component with `lstat`, rejects all symlinks, resolves the selected path, then verifies containment
using path semantics rather than string prefixes. The conservative no-symlink rule removes the
validation/open race that would otherwise allow a link target to change after authorization.

Consequences:

- `../secret`, absolute paths, prefix-confusion paths, and all symlinks are denied;
- the workspace root is resolved once during context validation and only that canonical root is used;
- special files, sockets, devices, and FIFOs are not read;
- generated output uses workspace-relative POSIX paths only;
- permission errors become sanitized failures without leaking host paths.

The guard is reusable by Phase 9 but does not create, mount, delete, or otherwise manage workspaces.

## Concrete tools

### `read_file`

Input: relative file path, one-based `start_line`, and `max_lines` from 1 through 2,000. It accepts
regular UTF-8 text files no larger than 8 MiB. It streams lines, returns at most 256 KiB of text, line
range metadata, and a truncation flag. Binary or invalid UTF-8 files fail safely; automatic encoding
guessing is excluded.

Required permission: `workspace.read`.

### `list_files`

Input: relative directory path, `recursive` flag, and `max_entries` from 1 through 10,000. It uses
bounded traversal, does not follow directory symlinks, sorts results deterministically, and returns
workspace-relative paths plus entry kinds. Hidden files are included because silently hiding project
configuration would make repository inspection unreliable. Escaping symlinks are never exposed as
readable targets.

Required permission: `workspace.list`.

### `search_text`

Input: non-blank literal query capped at 1,024 characters, relative directory/file path, optional
case sensitivity, `max_results` from 1 through 1,000, and per-line output capped at 4,096 characters.
It performs literal UTF-8 text search with bounded streaming, skips binary/special files, does not
follow directory symlinks, limits each candidate file to 8 MiB, and returns deterministic relative
path, line number, and bounded line text. Regex search is excluded from Phase 6 to avoid complexity
and denial-of-service behavior.

Required permission: `workspace.search`.

### `git_status`

Runs only `git status --short --branch --untracked-files=all` with a fixed argument vector, sanitized
environment, canonical workspace working directory, no shell, and bounded stdout/stderr. It returns
the bounded status text, exit code, and truncation metadata. The workspace must be inside a Git work
tree.

Required permission: `git.read`.

### `git_diff`

Input selects `WORKTREE` or `STAGED` and optional validated workspace-relative path filters. It runs
only one fixed form of `git diff --no-ext-diff --no-color --src-prefix=a/ --dst-prefix=b/`, adding
`--cached` for staged mode and `--` plus validated path filters. Git configuration disables external
diff and text conversion. Output is capped at 512 KiB and explicitly reports truncation.

Required permission: `git.read`.

## Resource lifecycle and process safety

- Each invocation executes one tool exactly once.
- Each tool has an enforced timeout no greater than 30 seconds.
- Cancellation is re-raised immediately after synchronous terminal audit staging; cleanup does not
  launch another task or shield long-running work.
- Git subprocesses use `asyncio.create_subprocess_exec`, a sanitized environment allowlist, a new
  process session, bounded capture, and explicit termination on timeout or cancellation.
- Files are opened with context managers and streamed; directory iterators are closed deterministically.
- Injected registries, recorders, sessions, and future clients are never closed by tools or executor.
- No retry, fallback command, network call, telemetry, or persistence occurs implicitly.

## Error model

Public failures use stable codes such as `TOOL_NOT_FOUND`, `TOOL_NOT_DECLARED`,
`PERMISSION_DENIED`, `INVALID_INPUT`, `WORKSPACE_VIOLATION`, `UNSUPPORTED_FILE`, `OUTPUT_LIMIT`,
`TOOL_FAILED`, `AUDIT_FAILED`, and `TOOL_TIMED_OUT`. Safe messages identify the class of failure, not
the rejected value. Internal exceptions are chained only where they cannot leak through public or
persisted representations.

Denied, failed, and timed-out calls are never represented as success. Cancellation remains
cancellation and is recorded as a cancelled audit result without changing the existing
`ToolCallStatus` enum; the `ToolCall` uses `FAILED` with safe code `CANCELLED` until a future schema
phase explicitly adds a cancellation state.

## Testing strategy

Tests follow strict red-green-refactor cycles.

Unit tests prove:

- strict models and schemas reject malformed or oversized data;
- duplicate registration fails and registry views are immutable;
- unknown, undeclared, and unauthorized tools never execute;
- each registered tool executes exactly once;
- timeout and cancellation stop execution without retry;
- paths reject absolute values, traversal, prefix confusion, and symlink escapes;
- filesystem tools enforce file, line, entry, result, and output limits;
- Git commands use fixed arguments, no shell, safe environment, and bounded output;
- errors and results do not expose absolute roots, raw rejected values, environment data, or secrets;
- injected dependencies remain open and caller-owned.

Real-PostgreSQL tests construct the schema exclusively through Alembic and prove:

- successful, denied, failed, timed-out, and cancelled attempts create the expected `ToolCall` and
  append-only `AuditEvent` records;
- persisted records contain only allowlisted metadata;
- raw file, diff, search, stderr, and argument contents are absent;
- the adapter never commits, rolls back, or closes the injected session.

The full repository test suite, Ruff check, Ruff format check, mypy, Alembic head verification, and
Docker health check are required before Phase 6 checkboxes are updated.

## Documentation and phase boundary

Phase 6 adds a tool-system usage document and an ADR for the registry/executor boundary. README and
`AGENTS.md` are updated to describe only verified Phase 6 behavior. Only Phase 6 checklist items are
checked after their acceptance evidence exists.

Phase 7 remains entirely unchecked and unimplemented. In particular, Phase 6 permission membership
is a deny-by-default prerequisite check, not the future Permission Engine.

## Acceptance criteria

Phase 6 is complete only when:

- the five approved read-only tools are explicitly registered and independently tested;
- every invocation passes through uniform declaration, permission, workspace, timeout, output, and
  audit enforcement;
- no arbitrary shell, filesystem write, network, MCP, skill, or autonomous behavior exists;
- all path and symlink escape tests pass;
- all audit integration tests pass against real PostgreSQL migrated by Alembic;
- the complete quality and container verification is green;
- only verified Phase 6 checklist boxes are checked;
- no Phase 7 behavior has been introduced.
