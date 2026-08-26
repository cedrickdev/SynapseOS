# Phase 6 Tool Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deny-by-default, audited registry and executor for five bounded read-only repository tools.

**Architecture:** Immutable core contracts describe tools, contexts, results, registry lookup, and audit lifecycle without importing infrastructure. A central executor performs declaration and permission checks, timeout/cancellation handling, and safe audit transitions; concrete filesystem, Git, and SQLAlchemy adapters live under `infrastructure/tools`.

**Tech Stack:** Python 3.12, asyncio, Pydantic v2, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-6-tool-registry-design.md`

## Global Constraints

- Implement Phase 6 only; do not add the Phase 7 Permission Engine, Agent integration, write tools, shell tools, MCP, skills, autonomous loops, or workspace lifecycle management.
- Keep code, comments, docstrings, migrations, and new documentation in English.
- Follow strict TDD: write one behavior test, observe the expected failure, implement the minimum, and rerun focused plus neighboring tests.
- Use real PostgreSQL migrated through Alembic for persistence tests; never use SQLite or `metadata.create_all()`.
- Allow exactly five read-only tools: `read_file`, `list_files`, `search_text`, `git_status`, and `git_diff`.
- Require canonical workspace containment, including resolved symlink checks, before any file or Git access.
- Never persist file contents, diff contents, search matches, raw subprocess streams, prompts, secrets, environment values, or absolute host paths.
- Enforce one execution attempt, no retries, a maximum 30-second timeout, bounded output, and immediate cancellation propagation.
- Never use `shell=True`, arbitrary command strings, user-controlled executables, or user-controlled environment values.
- Injected sessions, recorders, registries, and clients remain caller-owned and are never committed, rolled back, or closed by Phase 6 code.
- Preserve `CLAUDE.local.md` as untracked local state; never stage it.

---

### Task 1: Strict tool value objects and safe errors

**Files:**
- Create: `core/tools/types.py`
- Create: `core/tools/errors.py`
- Modify: `core/tools/__init__.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/test_types.py`

**Interfaces:**
- Produces `JsonValue`, `ToolRiskLevel`, `ToolResultStatus`, `ToolErrorCode`,
  `ToolExecutionContext`, and `ToolResult`.
- Produces sanitized `ToolError`, `ToolDefinitionError`, `ToolInputError`, `ToolWorkspaceError`, and `ToolAuditError` exceptions.

- [ ] **Step 1: Write failing enum and context tests**

```python
def test_execution_context_is_strict_frozen_and_bounded(tmp_path: Path) -> None:
    context = ToolExecutionContext(
        workspace_root=tmp_path,
        agent_id="backend-agent-03",
        agent_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        declared_tool_ids={"read_file"},
        permission_ids={"workspace.read"},
        correlation_id=uuid.uuid4(),
    )
    assert context.workspace_root == tmp_path.resolve()
    with pytest.raises(ValidationError):
        context.agent_id = "changed"  # type: ignore[misc]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/tools/test_types.py -q`  
Expected: collection fails because Phase 6 types do not exist.

- [ ] **Step 3: Implement strict frozen types**

Use `ConfigDict(frozen=True, extra="forbid")`, existing identifier syntax, immutable bounded sets, timezone-safe UUID fields, a canonical existing directory validator, finite non-negative duration, and a JSON-serializable output-size validator capped at 1 MiB.

```python
class ToolResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMED_OUT = "TIMED_OUT"


class ToolExecutionContext(_ImmutableToolModel):
    workspace_root: Path
    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    declared_tool_ids: IdentifierSet
    permission_ids: IdentifierSet
    correlation_id: UUID
```

- [ ] **Step 4: Add failure-shape and leak-resistance tests**

Assert blank/oversized identifiers, missing roots, files used as roots, extra fields, NaN durations, oversized output, output with unsupported values, and exception messages containing rejected values are refused safely.

- [ ] **Step 5: Implement minimal sanitized errors and result invariants**

Require successful results to have no error fields and unsuccessful results to have a stable `ToolErrorCode` plus bounded constant-safe message.

- [ ] **Step 6: Run focused tests and quality checks**

Run: `.venv/bin/pytest tests/tools/test_types.py -q`  
Run: `.venv/bin/ruff check core/tools tests/tools`  
Run: `.venv/bin/mypy core/tools tests/tools`

- [ ] **Step 7: Commit**

```bash
git add core/tools tests/tools
git commit -m "feat(tools): add strict tool runtime types"
```

---

### Task 2: Generic tool contract and immutable registry

**Files:**
- Create: `core/tools/tool.py`
- Create: `core/tools/registry.py`
- Modify: `core/tools/__init__.py`
- Create: `tests/tools/conftest.py`
- Create: `tests/tools/test_registry.py`

**Interfaces:**
- Produces `Tool[InputT]` with `name`, `description`, `input_type`, `required_permissions`, `risk_level`, `timeout_seconds`, and `execute(arguments, context)`.
- Produces `ToolRegistry.get(name)`, `ToolRegistry.names`, and `ToolRegistry.definitions` as immutable reads.

- [ ] **Step 1: Write a failing registry contract test**

```python
def test_registry_exposes_one_explicit_tool(fake_tool: FakeTool) -> None:
    registry = ToolRegistry([fake_tool])
    assert registry.get("fake_read") is fake_tool
    assert registry.names == ("fake_read",)
    assert registry.definitions[0].input_schema == FakeInput.model_json_schema()
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/tools/test_registry.py::test_registry_exposes_one_explicit_tool -q`  
Expected: failure because `Tool` and `ToolRegistry` do not exist.

- [ ] **Step 3: Implement the minimal generic contract and registry**

```python
class Tool[InputT: BaseModel](ABC):
    name: str
    description: str
    input_type: type[InputT]
    required_permissions: frozenset[str]
    risk_level: ToolRiskLevel
    timeout_seconds: float

    @abstractmethod
    async def execute(
        self, arguments: InputT, context: ToolExecutionContext
    ) -> Mapping[str, JsonValue]: ...
```

Construct a private mapping once, expose sorted immutable descriptors, and perform no dynamic import or later registration.

- [ ] **Step 4: Add descriptor and duplicate security tests**

Cover duplicate names, invalid names, blank/oversized descriptions, non-Pydantic input types, empty permissions, invalid permission IDs, timeout outside `(0, 30]`, mutable registry input after construction, and attempted mutation of descriptor views.

- [ ] **Step 5: Implement descriptor validation and immutable snapshots**

Reject invalid tools with `ToolDefinitionError` containing only a stable safe message.

- [ ] **Step 6: Run focused and neighboring tests**

Run: `.venv/bin/pytest tests/tools/test_registry.py tests/tools/test_types.py -q`  
Run: `.venv/bin/ruff check core/tools tests/tools`  
Run: `.venv/bin/mypy core/tools tests/tools`

- [ ] **Step 7: Commit**

```bash
git add core/tools tests/tools
git commit -m "feat(tools): add immutable tool registry"
```

---

### Task 3: Audit-neutral executor lifecycle

**Files:**
- Create: `core/tools/audit.py`
- Create: `core/tools/executor.py`
- Modify: `core/tools/__init__.py`
- Create: `tests/tools/test_executor.py`
- Modify: `tests/tools/conftest.py`

**Interfaces:**
- Produces `ToolAuditOutcome`, `ToolAuditHandle`, `ToolAuditStart`, `ToolAuditFinish`, and
  synchronous `ToolAuditRecorder.begin()` / `finish()` protocol methods. `ToolAuditOutcome` adds
  `CANCELLED` to the four public result outcomes because cancellation is propagated rather than
  returned as a `ToolResult`.
- Produces `ToolExecutor.execute(tool_name, arguments, context) -> ToolResult`.

- [ ] **Step 1: Write failing success-lifecycle test**

```python
def test_executor_calls_registered_tool_once_and_audits_success(
    executable_context: ToolExecutionContext,
) -> None:
    tool = CountingTool()
    recorder = RecordingAuditRecorder()
    result = asyncio.run(
        ToolExecutor(ToolRegistry([tool]), recorder).execute(
            "fake_read", {"path": "README.md"}, executable_context
        )
    )
    assert result.status is ToolResultStatus.SUCCEEDED
    assert tool.calls == 1
    assert recorder.events == ["begin", "finish:SUCCEEDED"]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/tools/test_executor.py::test_executor_calls_registered_tool_once_and_audits_success -q`  
Expected: failure because the executor and audit port do not exist.

- [ ] **Step 3: Implement one validated success path**

Begin audit before lookup using only tool name and argument key/type metadata, revalidate the registered input model with strict/forbid settings, call the tool once under `asyncio.timeout(tool.timeout_seconds)`, validate output, finish audit, and return `ToolResult`.

- [ ] **Step 4: Add deny-by-default tests**

Prove unknown, undeclared, missing-permission, extra-input, coercible-input, and malformed-output requests never execute and each valid-scope attempt finishes one audit with the expected safe code. Verify audit metadata contains argument keys/types but no values.

- [ ] **Step 5: Implement denial and failure mappings**

Map unknown tool to `TOOL_NOT_FOUND`, undeclared to `TOOL_NOT_DECLARED`, missing permissions to `PERMISSION_DENIED`, strict Pydantic rejection to `INVALID_INPUT`, tool domain errors to their stable code, and unexpected exceptions to `TOOL_FAILED` without class message leakage.

- [ ] **Step 6: Add timeout, cancellation, ownership, and no-retry tests**

Use event-driven async test doubles rather than sleeps. Assert timeout calls once and returns `TIMED_OUT`; cancellation stages a `CANCELLED` audit finish then re-raises `CancelledError`; begin-audit failure prevents execution; finish-audit failure raises `ToolAuditError`; and executor never calls `close`, `commit`, `rollback`, or retry methods.

- [ ] **Step 7: Implement timeout and cancellation cleanup**

Use `asyncio.timeout`; do not catch-and-convert `CancelledError`; synchronously finish cancellation audit and immediately re-raise. Clear references to raw arguments/results in failure paths.

- [ ] **Step 8: Run focused and full core tests**

Run: `.venv/bin/pytest tests/tools/test_executor.py tests/tools/test_registry.py tests/tools/test_types.py -q`  
Run: `.venv/bin/ruff check core/tools tests/tools`  
Run: `.venv/bin/mypy core/tools tests/tools`

- [ ] **Step 9: Commit**

```bash
git add core/tools tests/tools
git commit -m "feat(tools): enforce bounded tool execution"
```

---

### Task 4: Canonical workspace path guard

**Files:**
- Create: `infrastructure/tools/__init__.py`
- Create: `infrastructure/tools/paths.py`
- Create: `tests/tools/test_paths.py`

**Interfaces:**
- Produces `resolve_workspace_path(root, relative_path, *, must_exist, expected_kind)`.
- Produces `relative_workspace_path(root, resolved_path) -> str`.

- [ ] **Step 1: Write failing containment tests**

```python
@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "a/../../secret", "\x00bad"])
def test_path_guard_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ToolWorkspaceError, match="requested path is not allowed"):
        resolve_workspace_path(tmp_path, path, must_exist=True, expected_kind="file")
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/tools/test_paths.py -q`  
Expected: collection failure because the path guard does not exist.

- [ ] **Step 3: Implement lexical and canonical containment**

Reject blank, absolute, NUL, and `..` components before joining. Resolve the root and target with `Path.resolve(strict=must_exist)`, verify containment with `Path.is_relative_to`, validate regular-file/directory kind, and return no absolute path in exceptions.

- [ ] **Step 4: Add symlink, prefix-confusion, special-file, and race-oriented tests**

Create internal symlinks, file symlinks escaping the root, directory symlinks escaping the root, a sibling named with the root prefix, broken symlinks, and a FIFO where supported. Assert allowed internal symlinks resolve safely and all escapes/special files fail without leaking either root or target path.

- [ ] **Step 5: Implement safe relative rendering**

Return POSIX paths only after canonical containment. Never call string-prefix containment checks.

- [ ] **Step 6: Run focused quality checks**

Run: `.venv/bin/pytest tests/tools/test_paths.py -q`  
Run: `.venv/bin/ruff check infrastructure/tools tests/tools/test_paths.py`  
Run: `.venv/bin/mypy infrastructure/tools tests/tools/test_paths.py`

- [ ] **Step 7: Commit**

```bash
git add infrastructure/tools tests/tools/test_paths.py
git commit -m "feat(tools): secure workspace path resolution"
```

---

### Task 5: Bounded filesystem tools

**Files:**
- Create: `infrastructure/tools/filesystem.py`
- Modify: `infrastructure/tools/__init__.py`
- Create: `tests/tools/test_filesystem_tools.py`

**Interfaces:**
- Produces strict `ReadFileInput`, `ListFilesInput`, and `SearchTextInput`.
- Produces `ReadFileTool`, `ListFilesTool`, and `SearchTextTool`.

- [ ] **Step 1: Write failing `read_file` happy-path and bounds tests**

Create a UTF-8 fixture with numbered lines. Assert one-based slicing, relative path metadata, `workspace.read`, 256-KiB output cap, 8-MiB file cap, 2,000-line cap, truncation, binary/invalid UTF-8 rejection, special-file rejection, and symlink containment.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/tools/test_filesystem_tools.py -k read_file -q`  
Expected: failure because `ReadFileTool` does not exist.

- [ ] **Step 3: Implement streaming `ReadFileTool`**

Open only a guarded regular file with a context manager, stream incrementally, count UTF-8 encoded bytes before appending, and return `content`, `path`, `start_line`, `end_line`, `total_lines_observed`, and `truncated`.

- [ ] **Step 4: Write failing `list_files` tests**

Assert deterministic sorting, hidden-file inclusion, recursive/non-recursive behavior, entry-kind output, 10,000-entry and requested limits, no directory-symlink following, no host paths, and safe handling of permission failures.

- [ ] **Step 5: Implement bounded scandir traversal**

Use closed `os.scandir` iterators, a deterministic pending-directory queue, `follow_symlinks=False`, and stop immediately at the requested entry budget.

- [ ] **Step 6: Write failing `search_text` tests**

Assert literal matching, case behavior, file/directory roots, deterministic path/line order, line truncation at 4,096 characters, query length, 1,000-result cap, 8-MiB candidate cap, binary/invalid UTF-8 skipping, symlink escape prevention, and no regex interpretation.

- [ ] **Step 7: Implement streaming literal search**

Walk with the same guarded traversal primitives, read one line at a time, preserve line numbers, stop at the result budget, and return only bounded match text and relative paths.

- [ ] **Step 8: Run focused and tools tests**

Run: `.venv/bin/pytest tests/tools/test_filesystem_tools.py tests/tools/test_paths.py -q`  
Run: `.venv/bin/ruff check infrastructure/tools tests/tools`  
Run: `.venv/bin/mypy infrastructure/tools tests/tools`

- [ ] **Step 9: Commit**

```bash
git add infrastructure/tools tests/tools
git commit -m "feat(tools): add bounded filesystem readers"
```

---

### Task 6: Fixed-command bounded Git tools

**Files:**
- Create: `infrastructure/tools/git.py`
- Modify: `infrastructure/tools/__init__.py`
- Create: `tests/tools/test_git_tools.py`

**Interfaces:**
- Produces `GitStatusInput`, `GitDiffInput`, `GitDiffTarget`, `GitStatusTool`, and `GitDiffTool`.
- Internal `_run_git(args, workspace_root, output_limit)` accepts only adapter-owned argument tuples.

- [ ] **Step 1: Write failing `git_status` integration test**

Create a temporary local repository using test setup commands, then invoke the production tool and assert branch/status output, `git.read`, fixed action metadata, no shell, bounded output, and no absolute path.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/tools/test_git_tools.py -k status -q`  
Expected: failure because `GitStatusTool` does not exist.

- [ ] **Step 3: Implement one fixed status command**

Use `asyncio.create_subprocess_exec` with exactly `git status --short --branch --untracked-files=all`, `cwd` set to canonical root, `start_new_session=True`, stdin disabled, and an environment built only from safe platform necessities plus fixed Git hardening variables.

- [ ] **Step 4: Write failing `git_diff` tests**

Cover worktree/staged selection, multiple validated path filters, filenames beginning with `-` after `--`, no external diff/textconv/color, 512-KiB truncation, non-repository failure, non-zero exit, stderr redaction, timeout termination, cancellation termination, and exactly one subprocess.

- [ ] **Step 5: Implement fixed diff vectors and bounded subprocess collection**

Construct only adapter-owned switches. Validate every filter through the path guard before passing its relative form after `--`. Read stdout/stderr concurrently with caps, terminate the process group on timeout/cancellation, await process exit, and never retry.

- [ ] **Step 6: Add injected environment and command-leak tests**

Set hostile `GIT_EXTERNAL_DIFF`, `GIT_CONFIG_*`, `LD_PRELOAD`, `PYTHONPATH`, and secret-marker variables in the test process; prove they do not influence or appear in production output/audit metadata.

- [ ] **Step 7: Run focused checks**

Run: `.venv/bin/pytest tests/tools/test_git_tools.py -q`  
Run: `.venv/bin/ruff check infrastructure/tools/git.py tests/tools/test_git_tools.py`  
Run: `.venv/bin/mypy infrastructure/tools/git.py tests/tools/test_git_tools.py`

- [ ] **Step 8: Commit**

```bash
git add infrastructure/tools tests/tools/test_git_tools.py
git commit -m "feat(tools): add bounded git readers"
```

---

### Task 7: SQLAlchemy audit recorder and real-PostgreSQL execution tests

**Files:**
- Create: `infrastructure/tools/audit.py`
- Modify: `infrastructure/tools/__init__.py`
- Create: `tests/database/test_tool_execution.py`
- Create: `tests/database/tool_fixtures.py`

**Interfaces:**
- Produces `SQLAlchemyToolAuditRecorder(session: Session)` implementing the core audit port.
- Reuses existing `ToolCall`, `AuditEvent`, `ToolCallStatus`, `AuditActorType`, and `AuditResult` without schema changes.

- [ ] **Step 1: Write failing PostgreSQL success-audit test**

Create `Project`, `Agent`, `Task`, and `AgentRun`, flush them, execute a deterministic read-only fake tool, and assert one `ToolCall` transitions `RUNNING -> SUCCEEDED` and one append-only `AuditEvent` is staged with matching project/task/run/correlation scope.

- [ ] **Step 2: Verify RED against migrated PostgreSQL**

Run: `.venv/bin/pytest tests/database/test_tool_execution.py::test_successful_tool_execution_is_audited -q`  
Expected: failure because the SQLAlchemy recorder does not exist.

- [ ] **Step 3: Implement caller-owned audit staging**

`begin()` adds and flushes a `ToolCall` with UTC start time. `finish()` validates handle/session ownership, mutates terminal fields once, appends one `AuditEvent`, and does not commit, roll back, or close. Map statuses as follows:

```text
SUCCEEDED -> ToolCall SUCCEEDED / Audit SUCCEEDED
DENIED    -> ToolCall DENIED    / Audit DENIED
TIMED_OUT -> ToolCall TIMED_OUT / Audit FAILED
FAILED    -> ToolCall FAILED    / Audit FAILED
CANCELLED -> ToolCall FAILED    / Audit CANCELLED
```

- [ ] **Step 4: Add full terminal-state and allowlist tests**

Cover unknown, undeclared, permission denied, invalid input, workspace violation, tool failure, timeout, and cancellation. Assert persisted JSON contains only allowlisted keys/counts/types/relative paths/sizes/truncation/error codes and excludes supplied secret markers, contents, matches, diffs, stderr, raw argument values, absolute roots, and environment values.

- [ ] **Step 5: Add transaction and ownership tests**

Instrument session events to prove no commit/rollback/close; prove caller rollback removes both records; reject foreign-session, already-finished, detached, or unknown handles; and prove append-only protection still rejects AuditEvent mutation/deletion.

- [ ] **Step 6: Run PostgreSQL and neighboring suites**

Run: `.venv/bin/pytest tests/database/test_tool_execution.py tests/database/test_append_only.py tests/tools -q`  
Run: `.venv/bin/ruff check infrastructure/tools tests/database/test_tool_execution.py tests/tools`  
Run: `.venv/bin/mypy infrastructure/tools tests/database/test_tool_execution.py tests/tools`

- [ ] **Step 7: Commit**

```bash
git add infrastructure/tools tests/database/test_tool_execution.py tests/database/tool_fixtures.py
git commit -m "feat(tools): persist sanitized tool audits"
```

---

### Task 8: Default registry, documentation, checklist, and complete verification

**Files:**
- Modify: `infrastructure/tools/__init__.py`
- Create: `tests/tools/test_default_registry.py`
- Create: `docs/tools.md`
- Create: `docs/adr/0006-tool-registry-execution-boundary.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Produces `create_default_tool_registry() -> ToolRegistry` containing exactly the five approved read-only tools.
- Documents the public API, composition, permissions, audit behavior, bounds, and deliberate Phase 6 exclusions.

- [ ] **Step 1: Write failing default-registry acceptance test**

```python
def test_default_registry_contains_only_phase_6_tools() -> None:
    registry = create_default_tool_registry()
    assert registry.names == (
        "git_diff", "git_status", "list_files", "read_file", "search_text"
    )
```

Also assert exact required permissions, LOW risk, timeouts, strict input schemas, and absence of registration mutation methods.

- [ ] **Step 2: Verify RED and implement explicit composition**

Run: `.venv/bin/pytest tests/tools/test_default_registry.py -q`  
Expected: failure because the factory does not exist. Then instantiate the five concrete tools explicitly and rerun GREEN.

- [ ] **Step 3: Write documentation and ADR**

Document examples using an injected recorder/session, the executor-only invocation rule, all hard limits, path/symlink behavior, fixed Git commands, status/error mapping, caller-owned transactions, cancellation, and the Phase 7 boundary. Record rejected alternatives: registry-executes-everything and per-tool security/audit.

- [ ] **Step 4: Update repository status and only verified Phase 6 boxes**

Update README and AGENTS in English. Check only Phase 6 items proven by tests and implementation. Leave every Phase 7 and later checkbox unchanged. Do not add Context Intelligence implementation.

- [ ] **Step 5: Run fresh complete verification**

Run: `.venv/bin/pytest`  
Expected: all tests pass against real PostgreSQL with no warnings.

Run: `.venv/bin/ruff check .`  
Expected: `All checks passed!`

Run: `.venv/bin/ruff format --check .`  
Expected: every file already formatted.

Run: `.venv/bin/mypy .`  
Expected: no issues.

Run: `.venv/bin/alembic current`  
Expected: current revision is the repository head.

Run: `.venv/bin/alembic check`  
Expected: no new upgrade operations; Phase 6 requires no schema migration.

- [ ] **Step 6: Verify container and API health**

Run: `docker compose up -d --build`  
Run: `docker compose ps`  
Run: `curl --fail --silent http://localhost:8000/health`  
Expected: database and API healthy; health response is `{"status":"ok"}`.

- [ ] **Step 7: Perform scope, secret, and diff audit**

Run: `git diff --check`  
Run: `git status --short`  
Run: `git diff --name-only phase-5/agent-core...HEAD`  
Run a repository secret scan over tracked Phase 6 changes. Confirm no Phase 7 implementation, write/shell/MCP tool, raw-content persistence, generated report, or `CLAUDE.local.md` is tracked.

- [ ] **Step 8: Commit verified documentation**

```bash
git add README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md docs infrastructure/tools tests/tools tests/database/test_tool_execution.py tests/database/tool_fixtures.py core/tools
git commit -m "docs(tools): document Phase 6 tool registry"
```

Do not push or create a PR until the user explicitly requests branch integration.
