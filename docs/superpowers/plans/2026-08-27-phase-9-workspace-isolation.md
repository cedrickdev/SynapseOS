# Phase 9 Workspace and Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every persisted project one audited, resource-bounded, locally managed workspace without exposing write tools or arbitrary host access.

**Architecture:** Strict immutable core contracts define workspaces, operations, audit records, and the provider-neutral manager protocol. A local infrastructure backend owns deterministic project roots, atomic lock/staging/trash directories, secure Git import/clone, path containment, resource accounting, cleanup, and a SQLAlchemy append-only audit adapter.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio subprocesses, pathlib/os/stat/shutil, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-9-workspace-isolation-design.md`

## Global Constraints

- Implement Phase 9 only; no Phase 10 write tools, shell runner, Docker execution backend, MCP, retries, credentials, workspace table, or migration.
- Every final workspace is the canonical `projects/<project_uuid>` child of one configured managed base.
- Local repositories are imported through Git and never adopted in place; untracked source files are excluded.
- Remote clone accepts credential-free HTTPS URLs on an exact normalized hostname allowlist only.
- Every operation is finite: mandatory Git timeout, output cap, entry cap, byte cap, depth cap, local-root cap, and host cap.
- Git uses a fixed executable and structured arguments with no shell, hooks, credential helper, prompts, or implicit retry.
- Cancellation terminates the process immediately and cleans exact manager-owned staging state.
- Public errors and audit metadata never expose raw paths, URLs, Git output, file names/content, credentials, environment data, or internal exceptions.
- Injected process adapters and SQLAlchemy sessions are never closed; the manager/recorder never commits, rolls back, or owns caller transactions.
- Database tests use real PostgreSQL built by Alembic and never `metadata.create_all()`.
- Preserve the untracked user-owned `CLAUDE.local.md` file and never stage it.

## File structure

- Create `core/workspaces/__init__.py` — public Phase 9 core exports.
- Create `core/workspaces/errors.py` — stable sanitized exceptions.
- Create `core/workspaces/types.py` — immutable workspace, config, operation, audit, and resource value objects.
- Create `core/workspaces/manager.py` — asynchronous provider-neutral manager protocol.
- Create `core/workspaces/audit.py` — audit recorder protocol.
- Create `infrastructure/workspaces/__init__.py` — local adapter exports.
- Create `infrastructure/workspaces/git.py` — URL/source policy and bounded cancellable Git runner.
- Create `infrastructure/workspaces/filesystem.py` — managed layout, resource scan, secure removal, and path validation.
- Create `infrastructure/workspaces/audit.py` — SQLAlchemy append-only lifecycle recorder.
- Create `infrastructure/workspaces/local.py` — lifecycle orchestration and compensation.
- Create `tests/workspaces/` — isolated core/infrastructure tests.
- Create `tests/database/test_workspace_audit.py` — real-PostgreSQL audit integration tests.
- Create `docs/workspaces.md` and `docs/adr/0009-managed-project-workspaces.md`.
- Modify `core/config.py`, `infrastructure/tools/paths.py`, `README.md`, `AGENTS.md`, `docs/adr/README.md`, and Phase 9 only in `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`.

---

### Task 1: Strict workspace contracts

**Files:**
- Create: `core/workspaces/__init__.py`
- Create: `core/workspaces/errors.py`
- Create: `core/workspaces/types.py`
- Create: `core/workspaces/audit.py`
- Create: `core/workspaces/manager.py`
- Create: `tests/workspaces/__init__.py`
- Create: `tests/workspaces/test_types.py`

**Interfaces:**
- Consumes: `core.enums.AuditActorType`, `core.enums.AuditResult`, and the existing strict Pydantic conventions.
- Produces: `Workspace`, `WorkspaceProvenance`, `WorkspaceOperation`, `WorkspaceErrorCode`, `WorkspaceAuditContext`, `WorkspaceAuditRecord`, `WorkspaceResourceUsage`, `WorkspaceLimits`, `WorkspaceError`, `WorkspaceAuditRecorder`, and `WorkspaceManager`.

- [ ] **Step 1: Write failing strict-contract tests**

Create tests proving:

```python
def test_workspace_is_exact_frozen_and_canonical(tmp_path: Path) -> None:
    root = (tmp_path / "projects" / str(uuid4())).resolve()
    root.mkdir(parents=True)
    project_id = UUID(root.name)
    workspace = Workspace(
        project_id=project_id,
        root=root,
        provenance=WorkspaceProvenance.EMPTY,
    )
    assert workspace.root == root
    with pytest.raises(ValidationError):
        workspace.root = tmp_path  # type: ignore[misc]


def test_limits_are_finite_positive_and_bounded() -> None:
    limits = WorkspaceLimits(
        git_timeout_seconds=30.0,
        git_output_bytes=65_536,
        max_entries=100_000,
        max_total_bytes=1_073_741_824,
        max_depth=64,
        max_local_roots=32,
        max_remote_hosts=32,
    )
    assert limits.max_depth == 64
    for field in limits.model_fields:
        values = limits.model_dump()
        values[field] = 0
        with pytest.raises(ValidationError):
            WorkspaceLimits.model_validate(values, strict=True)
```

Also reject non-exact enum values, subclassed/forged models, non-canonical or missing roots, blank actor IDs, mismatched audit project IDs, NaN/inf durations, negative counts, unknown fields, mutable metadata, and secret markers in validation errors.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workspaces/test_types.py -q`
Expected: collection fails because `core.workspaces` does not exist.

- [ ] **Step 3: Implement strict immutable value objects and safe errors**

Use `ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)`. Define:

```python
class WorkspaceProvenance(StrEnum):
    EMPTY = "EMPTY"
    LOCAL_IMPORT = "LOCAL_IMPORT"
    REMOTE_CLONE = "REMOTE_CLONE"


class WorkspaceOperation(StrEnum):
    CREATE = "create_workspace"
    ATTACH = "attach_existing_repository"
    CLONE = "clone_repository"
    CLEANUP = "cleanup_workspace"


class WorkspaceErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    PROJECT_UNAVAILABLE = "PROJECT_UNAVAILABLE"
    WORKSPACE_EXISTS = "WORKSPACE_EXISTS"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
    UNSAFE_PATH = "UNSAFE_PATH"
    SOURCE_DENIED = "SOURCE_DENIED"
    REMOTE_DENIED = "REMOTE_DENIED"
    GIT_FAILED = "GIT_FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"
```

`WorkspaceLimits` uses explicit upper bounds: timeout ≤ 3,600 seconds, output ≤ 1 MiB, entries ≤ 1,000,000, bytes ≤ 1 TiB, depth ≤ 256, and allowlists ≤ 256 values. `WorkspaceAuditRecord.data` is a copied immutable mapping whose keys are restricted to `provenance`, `error_code`, `duration_ms`, `entry_count`, `total_bytes`, and `cleaned`.

- [ ] **Step 4: Define protocols**

```python
class WorkspaceAuditRecorder(Protocol):
    def record(self, record: WorkspaceAuditRecord) -> None: ...


class WorkspaceManager(Protocol):
    async def create_workspace(
        self, project_id: UUID, audit: WorkspaceAuditContext
    ) -> Workspace: ...
    async def attach_existing_repository(
        self, project_id: UUID, source: Path, audit: WorkspaceAuditContext
    ) -> Workspace: ...
    async def clone_repository(
        self, project_id: UUID, repository_url: str, audit: WorkspaceAuditContext
    ) -> Workspace: ...
    def validate_path(
        self,
        workspace: Workspace,
        relative_path: str,
        *,
        must_exist: bool,
        expected_kind: Literal["file", "directory", "any"],
    ) -> Path: ...
    async def cleanup_workspace(self, project_id: UUID, audit: WorkspaceAuditContext) -> None: ...
```

- [ ] **Step 5: Run focused quality checks**

Run: `.venv/bin/pytest tests/workspaces/test_types.py -q`
Run: `.venv/bin/ruff check core/workspaces tests/workspaces/test_types.py`
Run: `.venv/bin/mypy core/workspaces tests/workspaces/test_types.py`
Expected: all pass without warnings.

- [ ] **Step 6: Commit**

```bash
git add core/workspaces tests/workspaces
git commit -m "feat(workspaces): add strict lifecycle contracts"
```

---

### Task 2: Managed filesystem boundary

**Files:**
- Create: `infrastructure/workspaces/__init__.py`
- Create: `infrastructure/workspaces/filesystem.py`
- Create: `tests/workspaces/test_filesystem.py`
- Modify: `infrastructure/tools/paths.py`
- Modify: `tests/tools/test_paths.py`

**Interfaces:**
- Consumes: `Workspace`, `WorkspaceLimits`, `WorkspaceResourceUsage`, and existing `resolve_workspace_path()` semantics.
- Produces: `ManagedWorkspaceFilesystem` with `acquire_lock`, `release_lock`, `create_staging`, `promote`, `move_to_trash`, `remove_owned_tree`, `scan_usage`, `load_workspace`, and `validate_workspace_path`.

- [ ] **Step 1: Write failing filesystem security tests**

Test an initialized layout with mode `0o700`; deterministic project roots; atomic project lock collision; unique staging; exact promotion; canonical loading; path validation; non-following usage scan; special-file rejection; entry/byte/depth limits; symlinked base/trust-boundary rejection; forged workspace rejection; and cleanup refusal for base, manager directories, sibling paths, and mismatched UUID roots.

Include:

```python
def test_cleanup_can_only_remove_exact_manager_owned_project(tmp_path: Path) -> None:
    fs = _filesystem(tmp_path)
    project_id = uuid4()
    staging = fs.create_staging(project_id)
    final = fs.promote(project_id, staging)
    sibling = tmp_path / "must-survive"
    sibling.mkdir()
    trash = fs.move_to_trash(project_id)
    fs.remove_owned_tree(trash)
    assert not final.exists()
    assert sibling.exists()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workspaces/test_filesystem.py -q`
Expected: import failure because the workspace filesystem adapter is absent.

- [ ] **Step 3: Implement private managed layout and atomic locks**

Open/create base children with non-following checks and private permissions. Derive every name from an exact UUID. Acquire `.locks/<uuid>` using atomic `mkdir`; never infer or clear stale locks. Use random tokens only below `.staging` and `.trash`. Reject unexpected existing path kinds and links.

- [ ] **Step 4: Implement non-following scan and exact removal**

Walk with `os.scandir`, `entry.stat(follow_symlinks=False)`, a finite stack, and explicit depth/count/byte accounting. Count symlinks as inert entries, reject sockets/FIFOs/devices, and never traverse links. Removal walks bottom-up without following links and verifies the target remains a direct child of `.staging` or `.trash` before deleting.

- [ ] **Step 5: Reuse the Phase 6 path policy**

Extract a neutral internal containment primitive only if necessary while preserving public `resolve_workspace_path()` and `relative_workspace_path()` behavior. Workspace validation must call the same path policy; do not duplicate traversal rules.

- [ ] **Step 6: Run focused and regression checks**

Run: `.venv/bin/pytest tests/workspaces/test_filesystem.py tests/tools/test_paths.py -q`
Run: `.venv/bin/ruff check infrastructure/workspaces infrastructure/tools/paths.py tests/workspaces tests/tools/test_paths.py`
Run: `.venv/bin/mypy infrastructure/workspaces infrastructure/tools/paths.py tests/workspaces tests/tools/test_paths.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add infrastructure/workspaces infrastructure/tools/paths.py tests/workspaces/test_filesystem.py tests/tools/test_paths.py
git commit -m "feat(workspaces): enforce managed filesystem isolation"
```

---

### Task 3: Sanitized PostgreSQL workspace audit

**Files:**
- Create: `infrastructure/workspaces/audit.py`
- Create: `tests/database/test_workspace_audit.py`
- Modify: `infrastructure/workspaces/__init__.py`

**Interfaces:**
- Consumes: `WorkspaceAuditRecorder`, `WorkspaceAuditRecord`, existing `Project`, `AuditEvent`, and caller-owned `Session`.
- Produces: `SQLAlchemyWorkspaceAuditRecorder(session: Session)`.

- [ ] **Step 1: Write failing real-PostgreSQL tests**

Use the existing Alembic-built `db_session` fixture. Prove that exact records append:

```python
event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "WORKSPACE_LIFECYCLE"))
assert event is not None
assert event.action == "create_workspace"
assert event.resource_type == "WORKSPACE"
assert event.resource_id == str(project.id)
assert event.data == {
    "provenance": "EMPTY",
    "duration_ms": 4.0,
    "entry_count": 0,
    "total_bytes": 0,
}
```

Also prove project mismatch/absence fails closed, every result mapping is correct, secret/path/URL markers cannot enter persisted JSON, append-only protection applies, and `commit`, `rollback`, and `close` are never called.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/database/test_workspace_audit.py -q`
Expected: import failure because `SQLAlchemyWorkspaceAuditRecorder` is absent.

- [ ] **Step 3: Implement the recorder**

Validate exact model instances by reconstructing them strictly. Confirm `Project.id == record.context.project_id == record.project_id`, map the operation/result, add one `AuditEvent`, and flush. Catch internal exceptions and raise sanitized `WorkspaceError(AUDIT_FAILED, ...)` without owning transaction lifecycle.

- [ ] **Step 4: Run focused database checks**

Run: `.venv/bin/pytest tests/database/test_workspace_audit.py tests/database/test_append_only.py -q`
Run: `.venv/bin/ruff check infrastructure/workspaces/audit.py tests/database/test_workspace_audit.py`
Run: `.venv/bin/mypy infrastructure/workspaces/audit.py tests/database/test_workspace_audit.py`
Expected: all pass against PostgreSQL.

- [ ] **Step 5: Commit**

```bash
git add infrastructure/workspaces/audit.py infrastructure/workspaces/__init__.py tests/database/test_workspace_audit.py
git commit -m "feat(workspaces): audit lifecycle events"
```

---

### Task 4: Bounded Git import and clone boundary

**Files:**
- Create: `infrastructure/workspaces/git.py`
- Create: `tests/workspaces/test_git.py`
- Modify: `infrastructure/workspaces/__init__.py`

**Interfaces:**
- Consumes: `WorkspaceLimits` and sanitized workspace errors.
- Produces: `GitWorkspaceSource`, `AsyncGitWorkspaceClient`, `GitCloneResult`, `validate_local_source`, and `validate_remote_url`.

- [ ] **Step 1: Write failing local-source and URL policy tests**

Cover exact canonical allowlisted local roots, source outside allowlist, source inside managed base, symlinked roots/source/components, non-repositories, allowlist overflow, HTTPS normalization, exact hostname matching, IDNA, credentials, query, fragment, control characters, ports, non-HTTPS schemes, file/local/scp syntax, encoded separators/userinfo, and secret-free errors.

Use table-driven cases such as:

```python
@pytest.mark.parametrize(
    "url",
    [
        "file:///private/repo",
        "ssh://git@example.com/repo.git",
        "git@example.com:repo.git",
        "https://user:secret@example.com/repo.git",
        "https://example.com/repo.git?token=secret",
        "https://example.com/repo.git#fragment",
    ],
)
def test_remote_policy_rejects_unsafe_urls_without_echoing(url: str) -> None:
    with pytest.raises(WorkspaceError) as captured:
        validate_remote_url(url, frozenset({"example.com"}))
    assert "secret" not in str(captured.value)
```

- [ ] **Step 2: Write failing process-lifecycle tests**

With an injected subprocess factory, assert one fixed invocation, `shell=False` by construction, fixed `git -c credential.helper= -c core.hooksPath=/dev/null clone` arguments, local `--no-local`, no source mutation, bounded output, timeout termination, cancellation termination, no retry, safe error mapping, and no closure of injected factories.

- [ ] **Step 3: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workspaces/test_git.py -q`
Expected: import failure because the Git workspace adapter is absent.

- [ ] **Step 4: Implement validation and async runner**

Use `urllib.parse.urlsplit`, IDNA-normalized exact hosts, and explicit rejection before process creation. Use `asyncio.create_subprocess_exec` through an injectable factory, `asyncio.timeout`, concurrent bounded reads, and a `try/except CancelledError/finally` lifecycle that terminates then kills if required and always awaits process exit. Never include stdout/stderr or rejected input in errors.

- [ ] **Step 5: Verify with a real temporary local Git repository**

Create and commit a source fixture, add an untracked marker, import it with the real Git client, and assert committed files exist, the untracked marker is absent, Git objects are not hardlinked, and source status/refs/config remain unchanged.

- [ ] **Step 6: Run quality checks**

Run: `.venv/bin/pytest tests/workspaces/test_git.py -q`
Run: `.venv/bin/ruff check infrastructure/workspaces/git.py tests/workspaces/test_git.py`
Run: `.venv/bin/mypy infrastructure/workspaces/git.py tests/workspaces/test_git.py`
Expected: all pass without external network.

- [ ] **Step 7: Commit**

```bash
git add infrastructure/workspaces/git.py infrastructure/workspaces/__init__.py tests/workspaces/test_git.py
git commit -m "feat(workspaces): add bounded Git repository import"
```

---

### Task 5: Local manager creation and validation

**Files:**
- Create: `infrastructure/workspaces/local.py`
- Create: `tests/workspaces/fakes.py`
- Create: `tests/workspaces/test_local_manager.py`
- Modify: `infrastructure/workspaces/__init__.py`
- Modify: `core/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: all Task 1 protocols/types, `ManagedWorkspaceFilesystem`, Git client protocol, audit recorder, and `Settings`.
- Produces: `LocalWorkspaceManager` implementing `WorkspaceManager`, plus bounded environment-driven workspace defaults.

- [ ] **Step 1: Write failing creation/validation tests**

Prove that `create_workspace()` acquires/releases one lock, creates private staging, promotes once,
scans limits, records one success, returns an exact immutable canonical object, refuses absent project
through audit validation, refuses collisions/concurrency, cleans staging on every pre-promotion error,
compensates promotion when success audit fails, and exposes no path in failures.

- [ ] **Step 2: Write failing configuration tests**

Add settings with finite defaults:

```python
workspace_base_root: Path = Path(".synapseos/workspaces")
workspace_git_timeout_seconds: float = 120.0
workspace_git_output_bytes: int = 65_536
workspace_max_entries: int = 100_000
workspace_max_total_bytes: int = 1_073_741_824
workspace_max_depth: int = 64
workspace_local_import_roots: tuple[Path, ...] = ()
workspace_remote_hosts: tuple[str, ...] = ()
```

Tests reject zero, negative, non-finite, oversized, and overlong allowlists. Defaults keep local import and remote clone disabled.

- [ ] **Step 3: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workspaces/test_local_manager.py tests/test_config.py -q`
Expected: failures because manager and settings are absent.

- [ ] **Step 4: Implement creation orchestration**

Use one private `_provision(project_id, provenance, audit, populate)` method. Track exact created staging/final/trash paths locally, release the exact lock in `finally`, audit every terminal outcome once, and compensate a successful promotion if success auditing fails. Do not catch `CancelledError` as a generic failure.

- [ ] **Step 5: Implement strict workspace validation**

Require `type(workspace) is Workspace`, reconstruct strictly, call `load_workspace(project_id)` and compare canonical roots/provenance constraints, then delegate relative-path resolution to the shared path guard.

- [ ] **Step 6: Run focused quality checks**

Run: `.venv/bin/pytest tests/workspaces/test_local_manager.py tests/test_config.py tests/tools/test_paths.py -q`
Run: `.venv/bin/ruff check core/config.py infrastructure/workspaces/local.py tests/workspaces tests/test_config.py`
Run: `.venv/bin/mypy core/config.py infrastructure/workspaces/local.py tests/workspaces tests/test_config.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add core/config.py infrastructure/workspaces/local.py infrastructure/workspaces/__init__.py tests/test_config.py tests/workspaces
git commit -m "feat(workspaces): create isolated project roots"
```

---

### Task 6: Attach, clone, cleanup, and neighboring integration

**Files:**
- Modify: `infrastructure/workspaces/local.py`
- Modify: `tests/workspaces/test_local_manager.py`
- Create: `tests/workspaces/test_tool_compatibility.py`
- Modify: `tests/database/test_workspace_audit.py`

**Interfaces:**
- Consumes: `_provision`, Git client, managed filesystem, audit recorder, and Phase 6 read-only tools.
- Produces: complete `attach_existing_repository`, `clone_repository`, and `cleanup_workspace` behavior.

- [ ] **Step 1: Write failing attach and clone orchestration tests**

Assert local/remote validation occurs before staging and process calls; one Git call occurs; limits are checked after population; provenance is exact; errors/timeouts clean staging and audit once; cancellation cleans staging, audits cancellation, re-raises cancellation, and never retries; success audit failure compensates the promoted root.

- [ ] **Step 2: Write failing cleanup tests**

Assert exact lock acquisition, deterministic load, atomic move to trash, safe recursive removal, success audit, absent workspace failure audit, no arbitrary path input, refusal of symlink/mismatched roots, cleanup-failure audit, lock release, and no deletion outside manager roots.

- [ ] **Step 3: Write failing Phase 6 compatibility tests**

Create a workspace through the manager, place a read-only fixture during setup, build `ToolExecutionContext(workspace_root=workspace.root, ...)`, and prove existing `read_file`, `list_directory`, `search_text`, `git_status`, and `git_diff` preserve containment. Assert no new write tool is registered.

- [ ] **Step 4: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workspaces/test_local_manager.py tests/workspaces/test_tool_compatibility.py -q`
Expected: attach/clone/cleanup assertions fail because methods are incomplete.

- [ ] **Step 5: Implement attach and clone through `_provision`**

Pass only validated `GitWorkspaceSource` values into the Git client. Ensure the destination is the exact staging directory. Translate Git outcomes to stable workspace codes and permit no fallback from remote clone to local import or vice versa.

- [ ] **Step 6: Implement cleanup with compensation boundaries**

Acquire lock, load exact workspace, move exact final root to trash, delete without following links, append terminal audit, and release lock. If audit fails after deletion, return `AUDIT_FAILED`; never recreate stale content or report success.

- [ ] **Step 7: Run Phase 6–9 regression tests**

Run: `.venv/bin/pytest tests/workspaces tests/tools tests/permissions tests/skills tests/database/test_workspace_audit.py tests/database/test_tool_execution.py -q`
Run: `.venv/bin/ruff check core/workspaces infrastructure/workspaces tests/workspaces tests/database/test_workspace_audit.py`
Run: `.venv/bin/mypy core/workspaces infrastructure/workspaces tests/workspaces tests/database/test_workspace_audit.py`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add infrastructure/workspaces/local.py tests/workspaces tests/database/test_workspace_audit.py
git commit -m "feat(workspaces): complete audited workspace lifecycle"
```

---

### Task 7: Documentation, ADR, checklist, and final verification

**Files:**
- Create: `docs/workspaces.md`
- Create: `docs/adr/0009-managed-project-workspaces.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: verified Phase 9 behavior and commands.
- Produces: accurate operator/developer documentation and only genuinely completed Phase 9 checkboxes.

- [ ] **Step 1: Document the public boundary and operation examples**

Explain managed layout, immutable roots, default-disabled imports/clones, URL/source policy, limits, audit allowlist, cancellation, cleanup, configuration, and deliberate Phase 10 exclusions. Include no credential examples or host-specific absolute paths.

- [ ] **Step 2: Record ADR-0009**

Document why SynapseOS uses deterministic local roots without a workspace table, import-not-adopt semantics, atomic filesystem locks, append-only audit, and a provider-neutral manager contract for a future Docker backend.

- [ ] **Step 3: Update current-status documentation**

Update `README.md`, `AGENTS.md`, ADR index, and `.env.example`. Mark only the eight Phase 9 checklist items complete after mapping each item to tests. Leave Phase 10 and later untouched.

- [ ] **Step 4: Run focused verification**

Run: `.venv/bin/pytest tests/workspaces tests/database/test_workspace_audit.py tests/tools -q`
Expected: all pass without warnings.

- [ ] **Step 5: Run complete verification**

Run: `.venv/bin/pytest`
Expected: all tests pass against real PostgreSQL.

Run: `.venv/bin/ruff check .`
Expected: no findings.

Run: `.venv/bin/ruff format --check .`
Expected: every file formatted.

Run: `.venv/bin/mypy .`
Expected: strict typing passes.

Run: `git diff --check phase-8/skills-registry...HEAD`
Expected: no whitespace errors.

- [ ] **Step 6: Verify Docker and Alembic**

Run: `docker compose up -d --build`
Run: `docker compose exec -T api alembic current`
Expected: `20260826_0003 (head)` because Phase 9 has no migration.

Run: `docker compose exec -T api alembic check`
Expected: no new upgrade operations.

Run: `curl --fail --silent http://localhost:8000/health`
Expected: `{"status":"ok"}`.

- [ ] **Step 7: Run scope and security audit**

Verify no Phase 10 tools, shell runner, Docker execution backend, workspace table/migration, secrets, absolute-path audit data, raw Git output, retries, or Claude contributor/co-author trailers exist. Verify `CLAUDE.local.md` remains the only allowed untracked local file.

- [ ] **Step 8: Commit**

```bash
git add .env.example AGENTS.md README.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md docs
git commit -m "docs(workspaces): document verified Phase 9 isolation"
```

- [ ] **Step 9: Finish branch**

Push `phase-9/workspace-isolation` and create a stacked pull request with base `phase-8/skills-registry`. Do not merge and do not start Phase 10.
