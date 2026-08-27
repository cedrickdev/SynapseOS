# Phase 10 Transactional Write Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four bounded, authorized, audited, and compensatable UTF-8 file mutation tools inside managed project workspaces.

**Architecture:** Extend the existing tool result boundary with an optional transaction handle so the central executor can validate output, finalize PostgreSQL audit, then commit or restore the filesystem mutation. A focused local text transaction adapter performs non-following validation, bounded backup/replacement, atomic mutation, diff generation, and compensation; four small tool classes expose the behavior through the immutable registry.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, pathlib/os/stat/tempfile/difflib/hashlib, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-10-write-tools-design.md`

## Global Constraints

- Implement Phase 10 only; do not add shell execution, directory mutation, Git writes, MCP, Docker execution workspaces, autonomous loops, or Phase 11 behavior.
- Use English in code, comments, docstrings, tests, documentation, branches, and commits.
- Apply RED–GREEN–REFACTOR for every behavior; observe the focused test fail for the intended reason before production changes.
- PostgreSQL tests use the real Docker PostgreSQL service and Alembic only; never SQLite or `metadata.create_all()`.
- Every tool requires an exact managed workspace root and active persisted `filesystem.write` permission.
- Never follow links or mutate directories/special files; reject hard-linked regular files (`st_nlink != 1`).
- Never persist content, diffs, backup names, absolute paths, OS errors, credentials, prompts, or responses.
- Every byte count, patch count, diff, backup operation, timeout, and output is finite.
- Perform no implicit retry and no duplicate mutation attempt.
- Preserve caller ownership of SQLAlchemy sessions and injected resources.
- Never stage or commit `CLAUDE.local.md`; add no AI co-author or contributor trailer.

## File map

- `core/tools/tool.py` — generic plain/transactional tool execution return contract.
- `core/tools/types.py` — new stable error codes and unchanged bounded public `ToolResult`.
- `core/tools/executor.py` — transaction finalization/rollback around output validation and audit.
- `core/config.py` — finite Phase 10 limits.
- `infrastructure/tools/mutations.py` — filesystem transaction, exact patching, hashes, counters, and bounded diff.
- `infrastructure/tools/write.py` — strict inputs and four write tool adapters.
- `infrastructure/tools/__init__.py` — explicit immutable registry composition and exports.
- `infrastructure/permissions/policy.py` — deterministic risk-to-autonomy gate.
- `tests/tools/test_mutations.py` — low-level filesystem transaction/security tests.
- `tests/tools/test_write_tools.py` — contracts, outputs, limits, and registry tests.
- `tests/tools/test_executor.py` — transaction/audit ordering and compensation tests.
- `tests/database/test_permission_policy.py` — real-PostgreSQL risk authorization tests.
- `tests/database/test_write_tool_execution.py` — end-to-end real-PostgreSQL permission, mutation, and audit tests.
- `docs/write-tools.md`, `docs/adr/0010-transactional-write-tools.md` — operator and architectural documentation.
- `.env.example`, `README.md`, `AGENTS.md`, `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`, `docs/adr/README.md` — Phase 10 status/configuration updates.

---

### Task 1: Risk-sensitive permission decisions and finite settings

**Files:**
- Modify: `infrastructure/permissions/policy.py`
- Modify: `core/config.py`
- Modify: `.env.example`
- Test: `tests/database/test_permission_policy.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `PolicyRequest.risk_level: ToolRiskLevel`, existing persisted grants and agent autonomy.
- Produces: `_MINIMUM_RISK_AUTONOMY = {LOW: 0, MEDIUM: 1, HIGH: 2}` with `CRITICAL` always returning `ASK`; `Settings.write_*` bounded fields.

- [ ] **Step 1: Write failing PostgreSQL risk tests**

Add parameterized cases proving a granted `filesystem.write` request is `ASK` below the risk floor,
`ALLOW` at the floor, and always `ASK` for `CRITICAL`:

```python
@pytest.mark.parametrize(
    ("risk", "autonomy", "expected"),
    [
        (ToolRiskLevel.MEDIUM, 0, PermissionOutcome.ASK),
        (ToolRiskLevel.MEDIUM, 1, PermissionOutcome.ALLOW),
        (ToolRiskLevel.HIGH, 1, PermissionOutcome.ASK),
        (ToolRiskLevel.HIGH, 2, PermissionOutcome.ALLOW),
        (ToolRiskLevel.CRITICAL, 5, PermissionOutcome.ASK),
    ],
)
def test_policy_applies_risk_autonomy_gate(
    db_session: Session,
    risk: ToolRiskLevel,
    autonomy: int,
    expected: PermissionOutcome,
) -> None:
    scope = create_permission_scope(db_session, autonomy_level=autonomy)
    add_permission(db_session, scope, Permission.FILESYSTEM_WRITE)
    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        scope.request(
            frozenset({Permission.FILESYSTEM_WRITE}),
            risk_level=risk,
        ),
        scope.now,
    )
    assert decision.outcome is expected
```

- [ ] **Step 2: Run the focused risk test and observe RED**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_permission_policy.py -k risk_autonomy -q`

Expected: `MEDIUM`, `HIGH`, or `CRITICAL` cases incorrectly return `ALLOW` because risk is currently ignored.

- [ ] **Step 3: Implement the minimal risk gate**

After persisted grants and permission-level autonomy checks, return `ASK` when:

```python
if validated.risk_level is ToolRiskLevel.CRITICAL:
    return self._decision(
        validated,
        timestamp,
        PermissionOutcome.ASK,
        PermissionReasonCode.HUMAN_APPROVAL_REQUIRED,
        "Human approval is required.",
    )
if autonomy_level < _MINIMUM_RISK_AUTONOMY[validated.risk_level]:
    return self._decision(
        validated,
        timestamp,
        PermissionOutcome.ASK,
        PermissionReasonCode.AUTONOMY_APPROVAL_REQUIRED,
        "Additional approval is required for this autonomy level.",
    )
```

Keep production deployment's existing mandatory human approval rule stronger than this mapping.

- [ ] **Step 4: Write RED settings tests**

Assert defaults and rejection of zero/negative/excessive values for:

```python
write_max_input_bytes = 1_048_576
write_max_existing_bytes = 4_194_304
write_max_patch_operations = 128
write_max_patch_text_bytes = 262_144
write_max_diff_bytes = 262_144
write_timeout_seconds = 10.0
```

- [ ] **Step 5: Run settings tests and observe RED**

Run: `.venv/bin/pytest tests/test_config.py -k write -q`

Expected: fail because the fields do not exist.

- [ ] **Step 6: Add bounded Pydantic settings and GREEN both suites**

Use exact ceilings of 16 MiB for content limits, 1,024 operations, 1 MiB patch text/diff, and 60
seconds for timeout; require finite positive values and no unbounded override. Run:

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_permission_policy.py tests/test_config.py -q
.venv/bin/ruff check infrastructure/permissions/policy.py core/config.py tests/database/test_permission_policy.py tests/test_config.py
.venv/bin/mypy infrastructure/permissions/policy.py core/config.py
```

- [ ] **Step 7: Commit**

```bash
git add infrastructure/permissions/policy.py core/config.py .env.example tests/database/test_permission_policy.py tests/test_config.py
git commit -m "feat(permissions): enforce write tool risk gates"
```

### Task 2: Transactional tool execution contract

**Files:**
- Modify: `core/tools/tool.py`
- Modify: `core/tools/types.py`
- Modify: `core/tools/__init__.py`
- Modify: `core/tools/executor.py`
- Modify: existing tool and fake return annotations where required by mypy
- Test: `tests/tools/test_executor.py`
- Test: `tests/tools/fakes.py`

**Interfaces:**
- Produces: `ToolTransaction` protocol with synchronous `commit() -> None` and `rollback() -> None`.
- Produces: frozen `TransactionalToolOutput(output: Mapping[str, JsonValue], transaction: ToolTransaction)`.
- Changes: `Tool.execute(arguments, context) -> Mapping[str, JsonValue] | TransactionalToolOutput`.
- Produces error codes: `TARGET_NOT_FOUND`, `TARGET_CONFLICT`, `PATCH_MISMATCH`, `MUTATION_FAILED`, `COMPENSATION_FAILED`.

- [ ] **Step 1: Add a recording transaction fake and RED executor tests**

Cover exact ordering and one-call behavior:

```python
assert transaction.events == ["mutated", "audit_succeeded", "committed"]
assert tool.calls == 1
```

Add tests proving output validation failure, timeout, tool error, unexpected error, cancellation,
and audit finalization failure call `rollback()` exactly once and never `commit()`.

- [ ] **Step 2: Run focused executor tests and observe RED**

Run: `.venv/bin/pytest tests/tools/test_executor.py -k transaction -q`

Expected: import/contract failure because transactional outputs do not exist.

- [ ] **Step 3: Add minimal contracts and executor normalization**

Use a private normalized pair:

```python
def _unwrap_output(
    value: Mapping[str, JsonValue] | TransactionalToolOutput,
) -> tuple[Mapping[str, JsonValue], ToolTransaction | None]:
    if type(value) is TransactionalToolOutput:
        return value.output, value.transaction
    return value, None
```

The executor sequence is: execute once → validate bounded output → build `ToolResult` → finish
audit → transaction commit → return. Every exception after a transaction exists invokes one
rollback before returning/raising. Plain read-only mappings retain the exact existing path.

- [ ] **Step 4: Preserve cancellation and primary errors safely**

Use a focused `_rollback_or_raise(transaction, primary_code)` helper. If rollback fails, raise a
sanitized `ToolError(COMPENSATION_FAILED)`; otherwise preserve the original timeout, cancellation,
tool error, output-limit failure, or audit exception. Do not retry audit or mutation.

- [ ] **Step 5: Run executor regressions GREEN**

Run:

```bash
.venv/bin/pytest tests/tools/test_executor.py tests/tools/test_types.py tests/tools/test_default_registry.py -q
.venv/bin/ruff check core/tools tests/tools
.venv/bin/mypy core/tools tests/tools
```

- [ ] **Step 6: Commit**

```bash
git add core/tools tests/tools
git commit -m "feat(tools): add compensatable execution results"
```

### Task 3: Bounded local text transaction primitive

**Files:**
- Create: `infrastructure/tools/mutations.py`
- Test: `tests/tools/test_mutations.py`

**Interfaces:**
- Produces: frozen `MutationLimits`, `MutationOperation`, `MutationSummary`.
- Produces: `LocalTextMutator.replace(workspace_root, path, content)`,
  `.create(workspace_root, path, content)`, `.patch(workspace_root, path, operations)`, and
  `.delete(workspace_root, path)`, each returning `TransactionalToolOutput`.
- Consumes: canonical `workspace_root`, relative path, bounded UTF-8 content, exact patch tuple.

- [ ] **Step 1: Write RED success and rollback tests**

Prove replace/create/patch/delete mutate once, return relative metadata/hash/diff, retain a private
backup before commit, delete artifacts on commit, and restore exact bytes/mode on rollback.

- [ ] **Step 2: Run success tests and observe RED**

Run: `.venv/bin/pytest tests/tools/test_mutations.py -k 'success or rollback' -q`

Expected: module import failure.

- [ ] **Step 3: Implement bounded UTF-8 computation helpers**

Add helpers that:

```python
encoded = content.encode("utf-8")
if len(encoded) > limits.max_input_bytes:
    raise ToolError(ToolErrorCode.OUTPUT_LIMIT, "File content exceeds its limit.")
digest = hashlib.sha256(encoded).hexdigest()
```

Generate `difflib.unified_diff()` incrementally into a UTF-8-safe byte cap; continue only bounded
line accounting and set `diff_truncated=True` without accumulating the remainder.

- [ ] **Step 4: Implement private same-filesystem transaction artifacts**

Create random `0600` sibling files with
`os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)`, copy
and `fsync` original bytes into backup, write and `fsync` replacement, revalidate device/inode/type/
`st_nlink == 1`, then `os.replace`. Commit unlinks private artifacts; rollback restores with
`os.replace` or removes an exclusively created target. Directory handles and all file descriptors
close in `finally` blocks.

- [ ] **Step 5: Write and run RED security/limit tests**

Add traversal, absolute path, symlink target/parent, hard link, FIFO, directory, missing target,
create conflict, oversized existing/input, ambiguous/missing patch, no-op patch, replaced target,
and artifact-collision tests. Run:

` .venv/bin/pytest tests/tools/test_mutations.py -k 'security or limit or conflict or patch' -q`

Expected: each newly asserted guard fails before its implementation.

- [ ] **Step 6: Implement guards minimally and run GREEN**

Reuse `resolve_workspace_path`; use `os.lstat(target)` and
`os.stat(target, follow_symlinks=False)` with exact parent
containment. Never expose caught exception text or rejected values.

Run:

```bash
.venv/bin/pytest tests/tools/test_mutations.py -q
.venv/bin/ruff check infrastructure/tools/mutations.py tests/tools/test_mutations.py
.venv/bin/mypy infrastructure/tools/mutations.py tests/tools/test_mutations.py
```

- [ ] **Step 7: Commit**

```bash
git add infrastructure/tools/mutations.py tests/tools/test_mutations.py
git commit -m "feat(tools): add transactional text mutations"
```

### Task 4: Four strict write tool adapters

**Files:**
- Create: `infrastructure/tools/write.py`
- Modify: `infrastructure/tools/__init__.py`
- Modify: `tests/tools/test_default_registry.py`
- Create: `tests/tools/test_write_tools.py`

**Interfaces:**
- Produces: `WriteFileInput`, `CreateFileInput`, `PatchOperation`, `PatchFileInput`, `DeleteFileInput`.
- Produces: `WriteFileTool`, `CreateFileTool`, `PatchFileTool`, `DeleteFileTool`.
- Consumes: one injected `LocalTextMutator` configured from strict limits.

- [ ] **Step 1: Write RED strict input and definition tests**

Assert unknown fields/type coercion/absolute paths/oversized patch tuples fail validation. Assert
names, permission and risk:

```python
expected = {
    "write_file": (Permission.FILESYSTEM_WRITE, ToolRiskLevel.MEDIUM),
    "create_file": (Permission.FILESYSTEM_WRITE, ToolRiskLevel.MEDIUM),
    "patch_file": (Permission.FILESYSTEM_WRITE, ToolRiskLevel.MEDIUM),
    "delete_file": (Permission.FILESYSTEM_WRITE, ToolRiskLevel.HIGH),
}
```

- [ ] **Step 2: Run and observe RED**

Run: `.venv/bin/pytest tests/tools/test_write_tools.py tests/tools/test_default_registry.py -q`

Expected: missing write-tool classes and registry still contains five tools.

- [ ] **Step 3: Implement thin adapters and required registry injection**

Each adapter delegates exactly once and contains no filesystem logic. Change composition to:

```python
def create_default_tool_registry(write_mutator: LocalTextMutator) -> ToolRegistry:
    return ToolRegistry(
        [
            ReadFileTool(),
            ListFilesTool(),
            SearchTextTool(),
            GitStatusTool(),
            GitDiffTool(),
            WriteFileTool(write_mutator),
            CreateFileTool(write_mutator),
            PatchFileTool(write_mutator),
            DeleteFileTool(write_mutator),
        ]
    )
```

Required injection prevents a partially configured Phase 10 registry. Construction fails closed
unless the caller provides a mutator built from validated Phase 10 limits.

- [ ] **Step 4: Run adapter and registry tests GREEN**

Run:

```bash
.venv/bin/pytest tests/tools/test_write_tools.py tests/tools/test_default_registry.py -q
.venv/bin/ruff check infrastructure/tools/write.py infrastructure/tools/__init__.py tests/tools
.venv/bin/mypy infrastructure/tools/write.py infrastructure/tools/__init__.py
```

- [ ] **Step 5: Commit**

```bash
git add infrastructure/tools/write.py infrastructure/tools/__init__.py tests/tools/test_write_tools.py tests/tools/test_default_registry.py
git commit -m "feat(tools): add bounded file write adapters"
```

### Task 5: Executor compensation under audit, timeout, and cancellation

**Files:**
- Modify: `core/tools/executor.py`
- Modify: `tests/tools/test_executor.py`
- Modify: `tests/tools/test_write_tools.py`

**Interfaces:**
- Consumes: Task 2 transaction protocol and Task 3 mutation transactions.
- Produces: verified fail-closed lifecycle for real filesystem mutations.

- [ ] **Step 1: Write RED integration tests with real files and recording audit**

Test successful audit commits, audit finish failure restores, invalid oversized output restores,
timeout before mutation leaves state unchanged, and cancellation after mutation restores before
re-raising `CancelledError`. Assert no backup/replacement artifacts remain.

- [ ] **Step 2: Run focused tests and observe RED**

Run: `.venv/bin/pytest tests/tools/test_executor.py tests/tools/test_write_tools.py -k 'rollback or cancellation or audit_failure' -q`

Expected: at least the injected audit/cancellation boundary leaves mutation or artifact state.

- [ ] **Step 3: Implement cancellation-safe bounded compensation**

Capture the transaction immediately on return from `tool.execute`. On cancellation, use one shielded
bounded rollback call and then re-raise the original cancellation. Never shield the tool execution
itself and never repeat it.

- [ ] **Step 4: Run full tool suite GREEN**

Run:

```bash
.venv/bin/pytest tests/tools -q
.venv/bin/ruff check core/tools infrastructure/tools tests/tools
.venv/bin/ruff format --check core/tools infrastructure/tools tests/tools
.venv/bin/mypy core/tools infrastructure/tools tests/tools
```

- [ ] **Step 5: Commit**

```bash
git add core/tools/executor.py tests/tools/test_executor.py tests/tools/test_write_tools.py
git commit -m "fix(tools): restore mutations on terminal failure"
```

### Task 6: Real-PostgreSQL end-to-end write execution

**Files:**
- Create: `tests/database/test_write_tool_execution.py`
- Modify: `tests/database/tool_fixtures.py` only if a reusable autonomy/grant helper is required

**Interfaces:**
- Consumes: SQLAlchemy permission policy/audit, tool audit recorder, central executor, write tools,
  and real Alembic schema at `20260826_0003`.
- Produces: acceptance proof that filesystem mutation and sanitized append-only records agree.

- [ ] **Step 1: Write end-to-end PostgreSQL tests**

Create migrated Project/Agent/Task/AgentRun/grant fixtures and prove:

- `write_file`, `create_file`, `patch_file` execute for autonomy 1;
- `delete_file` returns `ASK` at autonomy 1 without mutation and executes at autonomy 2;
- missing/revoked/cross-project grants never mutate;
- every terminal result creates one sanitized `ToolCall`, permission audit, and `AuditEvent`;
- secret file content and diff markers are absent from every persisted JSON/text field;
- injected audit failure restores the file and the recorder never commits/rolls back/closes session.

- [ ] **Step 2: Run tests and observe RED where integration is incomplete**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_write_tool_execution.py -q`

- [ ] **Step 3: Make only focused integration corrections**

Correct contract mismatches in Task 1–5 code; add no migration and no API endpoint. Keep all session
lifecycle calls in the test/caller.

- [ ] **Step 4: Run Phase 6–10 database regressions GREEN**

Run:

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_permission_policy.py tests/database/test_permission_tool_execution.py tests/database/test_tool_execution.py tests/database/test_write_tool_execution.py tests/database/test_workspace_audit.py -q
.venv/bin/ruff check tests/database/test_write_tool_execution.py
.venv/bin/mypy tests/database/test_write_tool_execution.py
```

- [ ] **Step 5: Commit**

```bash
git add tests/database/test_write_tool_execution.py tests/database/tool_fixtures.py
git commit -m "test(tools): verify audited write execution"
```

### Task 7: Security and side-effect regression gate

**Files:**
- Modify: focused production/tests only if a regression exposes a Phase 10 defect
- Test: `tests/tools/test_mutations.py`
- Test: `tests/tools/test_write_tools.py`
- Test: `tests/workspaces/test_tool_compatibility.py`

**Interfaces:**
- Consumes: complete Phase 10 behavior.
- Produces: explicit proof of no host escape, leaked data, duplicate call, or read-tool regression.

- [ ] **Step 1: Add adversarial race and containment tests**

Use deterministic monkeypatch/barrier hooks to replace the target or parent after initial validation;
assert fail-closed behavior and no outside mutation. Verify hard links, symlinks, FIFOs, and sibling
workspaces remain untouched.

- [ ] **Step 2: Add boundedness and leak scans**

Assert maximum-size Unicode never splits in returned diff, transaction objects retain only bounded
original/replacement bytes, errors contain no markers, and persisted metadata includes no raw path,
content, diff, temporary name, or OS exception.

- [ ] **Step 3: Prove existing tools remain read-only and compatible**

Run managed workspaces through all five Phase 6 read tools before and after write-tool registration.
Assert registry construction requires a mutator, all nine tools are immutable after construction,
and no public registry mutation method exists.

- [ ] **Step 4: Run security regression suite GREEN**

Run:

```bash
.venv/bin/pytest tests/tools tests/workspaces tests/permissions -q
.venv/bin/ruff check core/tools infrastructure/tools tests/tools tests/workspaces tests/permissions
.venv/bin/mypy core/tools infrastructure/tools tests/tools tests/workspaces tests/permissions
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add core/tools infrastructure/tools tests/tools tests/workspaces tests/permissions
git commit -m "test(tools): harden write isolation regressions"
```

### Task 8: Documentation, checklist, and release verification

**Files:**
- Create: `docs/write-tools.md`
- Create: `docs/adr/0010-transactional-write-tools.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.env.example`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md` Phase 10 only

**Interfaces:**
- Consumes: verified implementation and exact final settings/behavior.
- Produces: Phase 10 operator guidance and evidence-backed completion state.

- [ ] **Step 1: Document operation and trust boundaries**

Explain strict contracts, permission/risk floors, atomic backup/rollback, limits, diff behavior,
sanitized audit, cancellation, configuration, injected write composition, local-filesystem limits,
and deliberate Phase 11 exclusions. Include no real secret, credential, or host-specific path.

- [ ] **Step 2: Record ADR-0010**

Document why exact replacement patches and compensatable local transactions were chosen over
arbitrary unified-diff parsing, direct writes, permanent backups, or early execution containers.

- [ ] **Step 3: Update status and Phase 10 checkboxes only**

Map each checklist item to a passing test before changing `[ ]` to `[x]`. Leave Phase 11 and later
sections byte-for-byte unchanged.

- [ ] **Step 4: Run complete acceptance verification**

Run fresh:

```bash
TEST_POSTGRES_PORT=55432 make check
.venv/bin/ruff format --check .
git diff --check
docker compose config --quiet
docker compose build api
docker compose up -d --no-deps api
curl --fail --silent --show-error http://localhost:8000/health
docker compose exec -T api alembic current
docker compose exec -T api alembic check
```

Expected: all tests pass against real PostgreSQL, Ruff/mypy are clean, image builds, API is healthy,
Alembic remains at existing head with no unintended upgrade operations.

- [ ] **Step 5: Run governance and scope scans**

Verify no Phase 11 runner, shell subprocess, secrets, raw content audit, retry loop, or Claude
contributor/co-author exists. Confirm `CLAUDE.local.md` is the only allowed untracked local file.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/write-tools.md docs/adr/0010-transactional-write-tools.md docs/adr/README.md README.md AGENTS.md .env.example SYNAPSEOS_DEVELOPMENT_CHECKLIST.md
git commit -m "docs(tools): complete Phase 10 guidance"
```

- [ ] **Step 7: Push and open stacked PR**

Push `phase-10/write-tools` and create a pull request with base `phase-9/workspace-isolation`.
Preserve the checkout for review and do not start Phase 11.
