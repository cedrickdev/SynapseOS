# Phase 11 Secure Command Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permissioned, audited, resource-bounded runner for immutable test, lint, build, and read-only Git command profiles without exposing a shell.

**Architecture:** Immutable core command contracts separate policy from execution. Infrastructure detects bounded stack markers, resolves only built-in profiles, and launches one argument-vector subprocess in the exact managed workspace with a sanitized environment, concurrent bounded stream capture, and complete timeout/cancellation cleanup. One `HIGH`-risk tool integrates the runner with the existing permission and PostgreSQL audit path.

**Tech Stack:** Python 3.12, asyncio subprocesses, Pydantic v2, pathlib/os/signal, FastAPI settings, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-11-secure-command-runner-design.md`

## Global Constraints

- Implement Phase 11 only; add no arbitrary command strings, arguments, shell operators, PTY, background tasks, Git mutations, dependency installation, network configuration, Docker execution backend, MCP, autonomous loop, or Phase 12 behavior.
- The model supplies only one closed `profile_id`; executable, argv, cwd, environment, timeout, and limits remain application-owned.
- Every invocation requires persisted `shell.execute`, `HIGH` risk, autonomy level 3, exact project scope, and the exact Phase 9 managed root.
- Use `asyncio.create_subprocess_exec`; never use `shell=True`, `create_subprocess_shell`, `os.system`, or command-string parsing.
- Launch exactly once, close stdin, use a new process session, inherit no uncontrolled environment values, retry nothing, and propagate cancellation after bounded cleanup.
- Bound timeout, retained stdout/stderr, marker bytes, read chunks, and termination grace with finite positive settings and hard maxima.
- Drain stdout/stderr concurrently even after retention caps to prevent deadlock; never persist raw output, argv, executable paths, cwd, marker contents, environment values, OS errors, prompts, or responses.
- A non-zero exit code is observable command output, never a concealed failure.
- Injected collaborators and caller-owned SQLAlchemy sessions are never closed, committed, or rolled back by command components.
- Tests use real behavior where deterministic and real PostgreSQL built exclusively through Alembic for persistence coverage.
- Keep all code, comments, identifiers, documentation, commits, and PR text in English. Never track `CLAUDE.local.md` or add Claude/Anthropic contributor trailers.

---

### Task 1: Immutable command contracts and limits

**Files:**
- Create: `core/commands/__init__.py`
- Create: `core/commands/errors.py`
- Create: `core/commands/types.py`
- Create: `core/commands/ports.py`
- Test: `tests/commands/test_types.py`
- Modify: `core/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `CommandProfileId`, `CommandCategory`, `CommandTerminalStatus`, `CommandLimits`, `CommandSpec`, `CommandResult`, `CommandErrorCode`, `CommandError`, `CommandPolicy.resolve(profile_id, workspace_root) -> CommandSpec`, and `CommandRunner.run(spec) -> CommandResult`.
- `CommandSpec` owns `profile_id`, `category`, immutable absolute executable, immutable argument tuple, exact workspace root, immutable environment mapping, timeout, stdout/stderr limits, read chunk size, and termination grace.
- `CommandResult` owns profile/category, exit code, bounded strings, independent truncation flags, non-negative duration, and terminal status.

- [ ] **Step 1: Write RED contract tests**

Assert exact profile values `pytest`, `ruff`, `mypy`, `npm-test`, `npm-build`, `php-artisan-test`, `git-status`, `git-diff`, `git-diff-staged`, and `git-log`; immutable tuples/mappings; rejection of relative executables/workspaces, empty argv/environment keys, non-finite or out-of-range limits, negative duration, invalid exit code/status combinations, and mutable input after construction. Name the production validator that each test proves.

- [ ] **Step 2: Run RED tests**

Run: `.venv/bin/pytest tests/commands/test_types.py -q`  
Expected: collection fails because `core.commands` does not exist.

- [ ] **Step 3: Implement minimal contracts**

Use frozen Pydantic models with `extra="forbid"`, hidden inputs in validation errors, tuple coercion before validation, and `MappingProxyType(dict(value))` copies. Define stable codes: `UNKNOWN_PROFILE`, `PROFILE_UNAVAILABLE`, `WORKSPACE_INVALID`, `MARKER_INVALID`, `EXECUTABLE_UNAVAILABLE`, `SPAWN_FAILED`, `TIMED_OUT`, `TERMINATION_FAILED`, and `RESULT_INVALID`. Messages are fixed and carry no raw cause.

- [ ] **Step 4: Add RED bounded-settings tests**

Test defaults and environment overrides for command timeout, stdout bytes, stderr bytes, marker bytes, chunk bytes, and termination grace. Reject zero, negative, infinite, NaN, and values over hard maxima.

- [ ] **Step 5: Implement settings and document environment keys**

Add `command_timeout_seconds` `(0, 30]`, retained stream limits `(0, 1 MiB]`, marker limit `(0, 1 MiB]`, chunk limit `(0, 64 KiB]`, and termination grace `(0, 5]` with conservative defaults. Add placeholder-free `.env.example` entries.

- [ ] **Step 6: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/commands/test_types.py tests/test_config.py -q`  
Expected: PASS without warnings.

Commit: `feat(commands): define bounded runner contracts`

---

### Task 2: Immutable profile catalog and deterministic detection

**Files:**
- Create: `infrastructure/commands/__init__.py`
- Create: `infrastructure/commands/catalog.py`
- Create: `infrastructure/commands/policy.py`
- Test: `tests/commands/test_policy.py`
- Reuse: `infrastructure/workspaces/filesystem.py`

**Interfaces:**
- Consumes: Task 1 contracts and `ManagedWorkspaceFilesystem.require_managed_root(path)`.
- Produces: `BuiltinCommandCatalog`, `LocalCommandPolicy(filesystem, limits, executable_resolver=None)`, and an injectable resolver protocol used only to make executable availability deterministic in tests.

- [ ] **Step 1: Write RED catalog tests**

Assert the exact ten profile IDs, categories, fixed argv, no mutation API, no duplicate IDs, Python vectors based on `sys.executable`, fixed Git hardening arguments, and no user-supplied command fragments.

- [ ] **Step 2: Run RED catalog tests**

Run: `.venv/bin/pytest tests/commands/test_policy.py -q`  
Expected: FAIL because infrastructure command policy is missing.

- [ ] **Step 3: Implement the immutable catalog**

Store adapter-owned templates only. Git vectors must disable external diff/textconv/color, paging, prompts, optional locks, and global/system configuration. Bound `git-log` with a fixed record count and fixed format. Do not reuse a shell command string.

- [ ] **Step 4: Write RED marker and workspace tests**

Use real temporary managed roots. Assert Python profiles require a bounded regular non-symlink `pyproject.toml`; npm profiles require bounded valid JSON with the exact script key; Artisan requires bounded `composer.json` plus a regular non-symlink `artisan`; Git profiles require a non-symlink `.git` directory or a bounded regular `.git` worktree pointer file. Reject forged roots, subdirectories, missing/malformed/oversized/symlink markers, absent scripts, and unavailable executables before runner invocation.

- [ ] **Step 5: Implement bounded policy resolution**

Read marker bytes at most `marker_limit + 1`, parse TOML/JSON as data, never import or execute content, and copy no marker values into errors. Resolve npm, PHP, and Git only through fixed approved absolute directories and return one immutable `CommandSpec` with exact managed cwd and sanitized fixed environment.

- [ ] **Step 6: Add platform and environment regression tests**

Assert Linux/macOS approved directories are deterministic, parent secret/proxy/Python/package-manager variables do not enter the child environment, no repository value changes argv/environment, and resolver injection is never closed.

- [ ] **Step 7: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/commands/test_policy.py -q`  
Expected: PASS without warnings.

Commit: `feat(commands): add immutable command profiles`

---

### Task 3: Bounded local asynchronous runner

**Files:**
- Create: `infrastructure/commands/runner.py`
- Test: `tests/commands/test_runner.py`

**Interfaces:**
- Consumes: `CommandSpec`, `CommandResult`, and stable errors from Task 1.
- Produces: `LocalCommandRunner(process_factory=asyncio.create_subprocess_exec)` implementing `CommandRunner.run(spec)`.

- [ ] **Step 1: Write RED real-process result tests**

Using fixed test-owned Python scripts as already-resolved vectors, assert exact cwd, stdin EOF, separate stdout/stderr, UTF-8 replacement, exit code 0 and non-zero preservation, measured duration, and one returned terminal result.

- [ ] **Step 2: Run RED result tests**

Run: `.venv/bin/pytest tests/commands/test_runner.py -q`  
Expected: FAIL because `LocalCommandRunner` is missing.

- [ ] **Step 3: Implement one no-shell launch**

Call the injected exec-style factory once with `str(spec.executable), *spec.arguments`, exact cwd/environment, `DEVNULL`, two pipes, `start_new_session=True`, and no shell parameter. Validate the returned result through `CommandResult`.

- [ ] **Step 4: Write RED bounded-stream tests**

Generate stdout and stderr larger than independent caps concurrently. Assert retained UTF-8 byte lengths never exceed limits, both streams are fully drained, each truncation flag is independent, and retained memory does not grow with total generated output.

- [ ] **Step 5: Implement concurrent bounded draining**

Use two tasks reading at most `read_chunk_bytes` per call. Retain byte prefixes only up to each cap, keep draining to EOF, decode after truncation with replacement, and await process plus readers together.

- [ ] **Step 6: Write RED timeout/cancellation/descendant tests**

Use event-driven real child/descendant processes where portable and deterministic fake process adapters for the escalation branch. Assert timeout kills the process group, cancellation kills/reaps it then re-raises, TERM grace escalates to KILL, spawn/termination errors are sanitized, pending reader tasks are cancelled/awaited, one spawn occurs, and no retry or fallback occurs.

- [ ] **Step 7: Implement bounded cleanup**

Wrap the complete wait/drain lifecycle in `asyncio.timeout(spec.timeout_seconds)`. On timeout or cancellation, signal the process group, await within termination grace, escalate to kill, reap, cancel/await stream tasks, and preserve cancellation. Map raw OS/runtime failures to stable errors after deleting references to causes.

- [ ] **Step 8: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/commands/test_runner.py -q`  
Expected: PASS without warnings and no surviving child process.

Commit: `feat(commands): add bounded local process runner`

---

### Task 4: Permissioned command-profile tool

**Files:**
- Create: `infrastructure/tools/command.py`
- Modify: `infrastructure/tools/__init__.py`
- Modify: `tests/tools/test_registry.py`
- Create: `tests/tools/test_command_tool.py`
- Modify: every existing `create_default_tool_registry(...)` call site to inject the command service explicitly.

**Interfaces:**
- Consumes: `CommandPolicy`, `CommandRunner`, and existing `ToolExecutionContext`.
- Produces: strict frozen `RunCommandProfileInput(profile_id)` and `RunCommandProfileTool(policy, runner)` named `run_command_profile`, requiring `{Permission.SHELL_EXECUTE}`, `HIGH` risk, timeout no greater than 30 seconds.

- [ ] **Step 1: Write RED strict-input and declaration tests**

Assert only `profile_id` is accepted; command, args, cwd, environment, timeout, limits, and extra fields fail strict validation. Assert exact name, permission, risk, timeout, description, and immutable default registry now containing ten tools.

- [ ] **Step 2: Run RED declaration tests**

Run: `.venv/bin/pytest tests/tools/test_command_tool.py tests/tools/test_registry.py -q`  
Expected: FAIL because the command tool is absent.

- [ ] **Step 3: Implement the thin adapter and explicit registry injection**

Resolve exactly one profile from `context.workspace_root`, call `runner.run(spec)` once, and return only the bounded result fields. Do not catch cancellation, retry, persist, construct sessions, or own injected collaborators. Require both write mutator and command service when constructing the default registry so omission cannot silently reduce the security surface.

- [ ] **Step 4: Write RED adapter behavior tests**

Assert policy rejection prevents runner invocation; valid resolution passes the exact immutable spec once; non-zero exits remain output; command errors retain stable codes; cancellation propagates; and neither policy nor runner receives close/commit/rollback calls.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/tools/test_command_tool.py tests/tools/test_registry.py tests/skills/test_builtin_skills.py -q`  
Expected: PASS without warnings.

Commit: `feat(tools): register secure command profiles`

---

### Task 5: Permission and audit integration on real PostgreSQL

**Files:**
- Create: `tests/database/test_command_tool_execution.py`
- Modify: `infrastructure/tools/audit.py` only if a new bounded result classification needs allowlisting.
- Modify: `infrastructure/permissions/policy.py` only if regression evidence shows `HIGH` risk is not already enforced at autonomy 3.

**Interfaces:**
- Consumes: migrated PostgreSQL fixtures, `PermissionEngine`, `ToolExecutor`, `RunCommandProfileTool`, `LocalCommandPolicy`, and `LocalCommandRunner`.
- Produces: proven end-to-end authorization and sanitized audit behavior without schema changes.

- [ ] **Step 1: Write RED persisted-authorization tests**

Create real Agent/Project/Task/AgentRun rows through migrated PostgreSQL. Assert an active project-scoped `shell.execute` grant plus autonomy 3 permits one profile; missing, expired, revoked, cross-project, and autonomy below 3 never invoke the runner and persist the existing denial/ask lifecycle.

- [ ] **Step 2: Run RED integration tests**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_command_tool_execution.py -q`  
Expected: FAIL because command execution is not wired into the audited tool path.

- [ ] **Step 3: Implement only required audit allowlisting**

Persist profile/category, terminal classification, exit-code class, duration milliseconds, stdout/stderr byte counts, and truncation booleans only. Keep existing caller-owned transaction behavior. Add no migration and no raw command result persistence.

- [ ] **Step 4: Add RED leak/failure/cancellation tests**

Place unique secret markers in stdout, stderr, environment, workspace path, marker files, and sanitized OS errors. Assert none occur in `ToolCall`, `AuditEvent`, exceptions, or metadata. Assert non-zero result is visible and audited, timeout gets one terminal audit, cancellation gets `CANCELLED` then re-raises, and no session commit/rollback/close occurs.

- [ ] **Step 5: Verify GREEN and commit**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_command_tool_execution.py tests/database/test_permission_tool_execution.py tests/database/test_tool_execution.py -q`  
Expected: PASS without warnings.

Commit: `test(commands): verify audited profile execution`

---

### Task 6: Security, compatibility, and real-profile acceptance

**Files:**
- Create: `tests/commands/test_security.py`
- Create: `tests/commands/test_profiles_integration.py`
- Modify: `Dockerfile` only if the existing Python tooling needed by fixed profiles is absent from the runtime image and the change remains within Phase 11.

**Interfaces:**
- Consumes: complete Phase 11 command stack.
- Produces: adversarial and available-runtime acceptance evidence.

- [ ] **Step 1: Write adversarial RED tests**

Attempt shell metacharacters, newline injection, option injection, executable replacement, PATH poisoning, symlink marker/root swaps, cwd substitution, environment inheritance, oversized streams/markers, interactive reads, forked descendants, and profile mismatch. Assert every case is either structurally unrepresentable or fails before spawn with a stable error.

- [ ] **Step 2: Run RED security tests**

Run: `.venv/bin/pytest tests/commands/test_security.py -q`  
Expected: at least one intended security assertion fails before hardening.

- [ ] **Step 3: Apply minimal hardening**

Fix only reproduced gaps at the narrowest policy/runner boundary. Do not add command parsing, heuristic sanitization, or unrelated refactors.

- [ ] **Step 4: Add real-profile smoke tests**

Run available Python and Git profiles in disposable managed repositories and assert deterministic results. Skip npm/PHP only when their trusted executable is absent; when present, use bounded disposable marker projects. Never install dependencies or access the network.

- [ ] **Step 5: Verify focused Phase 11 suite and commit**

Run: `.venv/bin/pytest tests/commands tests/tools/test_command_tool.py tests/database/test_command_tool_execution.py -q`  
Expected: PASS without warnings.

Commit: `test(commands): harden runner isolation`

---

### Task 7: Documentation, checklist, and complete verification

**Files:**
- Create: `docs/commands.md`
- Create: `docs/adr/0011-secure-command-runner.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md` Phase 11 section only

**Interfaces:**
- Consumes: verified Phase 11 behavior and exact commands.
- Produces: operator guidance, architecture rationale, truthful checklist state, and delivery evidence.

- [ ] **Step 1: Document the exact boundary**

Document every profile/vector/category/evidence rule, permission/autonomy/risk gate, settings and hard maxima, sanitized environment, result semantics, output truncation, timeout/cancellation cleanup, audit allowlist, known application-level sandbox limitation, and examples using executor-owned invocation. State explicitly that arbitrary shell, background tasks, dynamic arguments, network enablement, Git writes, and Phase 12 are absent.

- [ ] **Step 2: Record ADR-0011**

Record why immutable profiles were selected over Claude-Code-style free-form Bash in this phase, which lifecycle patterns were retained, why repository test/build scripts remain `HIGH` risk, and why OS/container sandboxing is required before untrusted production workloads.

- [ ] **Step 3: Update repository status and Phase 11 boxes only**

Update README and AGENTS commands/layout/status. Check each Phase 11 box only after its acceptance evidence exists. Do not edit Phase 12 or later checklist sections.

- [ ] **Step 4: Run complete fresh verification**

Run:

```bash
TEST_POSTGRES_PORT=55432 make check
.venv/bin/ruff format --check .
git diff --check
docker compose config --quiet
docker compose build api
docker compose up -d --no-deps api
docker compose ps
docker compose exec -T api alembic current
docker compose exec -T api alembic check
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

Expected: Ruff passes; strict mypy has no issues; all pytest tests pass against real PostgreSQL; formatting and whitespace checks pass; API and PostgreSQL are healthy; Alembic is at one head with no pending operations; health returns `{"status":"ok"}`.

- [ ] **Step 5: Run delivery security gates**

Verify no Phase 12 code, arbitrary shell API, `shell=True`, command-string parser, retry loop, background process, secrets, raw command output persistence, absolute-path audit data, Claude/Anthropic contributor trailer, or tracked `CLAUDE.local.md` exists. Verify branch history contains only expected English conventional commits.

- [ ] **Step 6: Commit documentation**

Commit: `docs(commands): complete Phase 11 guidance`

- [ ] **Step 7: Push and open a stacked PR**

Push `phase-11/secure-command-runner` and open a PR targeting `phase-10/write-tools`. Include the exact verification evidence, security boundary, and explicit statement that Phase 12 was not started.
