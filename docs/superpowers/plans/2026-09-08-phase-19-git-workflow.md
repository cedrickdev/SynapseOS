# Phase 19 Git Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a bounded, audited, provider-neutral local Git workflow for dedicated task
branches, explicit-path commits, status, diff, history, pull-request preparation, and deterministic
merge-requirement validation.

**Architecture:** `core/git_workflow/` owns immutable contracts, validation, orchestration, and the
provider/audit ports. `infrastructure/git/` owns the fixed-command local Git adapter, secret-aware
commit policy, and SQLAlchemy audit recorder. Existing workspace path validation, Phase 18 local
secret sanitization, and append-only `AuditEvent` persistence are reused without introducing a new
database model.

**Tech Stack:** Python 3.12+, Pydantic v2, asyncio subprocesses, SQLAlchemy 2, PostgreSQL 16,
Alembic, pytest, Ruff, and strict mypy.

**Spec:** `docs/superpowers/specs/2026-09-08-phase-19-git-workflow-design.md`

## Global Constraints

- Implement Phase 19 only; Phase 20 pull-request persistence, remote providers, push, fetch, merge,
  and remote branch protection remain absent.
- Use English in code, comments, tests, documentation, branch names, and commit messages.
- Follow strict RED, GREEN, REFACTOR TDD; observe every behavioral test fail before production code.
- Use only real temporary Git repositories for Git behavior and real PostgreSQL built through
  Alembic for persistence tests.
- Every collection, string, process output, result, and timeout is finite and validated.
- No shell, arbitrary Git arguments, inherited credentials, retries, duplicate calls, or hidden
  fallbacks.
- Cancellation terminates the child process and propagates without later database work.
- Never stage, revert, clean, stash, delete, or commit files outside the explicit request paths.
- Never store raw diffs, file paths, commit subjects, process output, credentials, or exceptions in
  audit metadata.
- Do not modify the existing Phase 20 or later checklist boxes.

---

### Task 1: Define strict Git workflow contracts

**Files:**

- Create: `core/git_workflow/__init__.py`
- Create: `core/git_workflow/errors.py`
- Create: `core/git_workflow/types.py`
- Create: `tests/git_workflow/__init__.py`
- Create: `tests/git_workflow/factories.py`
- Create: `tests/git_workflow/test_types.py`

**Interfaces:**

- Produces `GitWorkflowError(code, message)`, `GitWorkflowErrorCode`, and immutable public models.
- Produces `derive_task_branch(task_id, kind, slug) -> TaskBranchName` for later validation.
- Produces exact enums `GitOperation`, `TaskBranchKind`, `GitDiffMode`, `GitCheckStatus`, and
  `MergeDecision`.
- Produces `GitWorkflowContext`, `GitIdentity`, operation request/result models,
  `PullRequestPreparation`, `MergeEvidence`, and `MergeValidationResult`.

- [x] **Step 1: Write failing branch and immutable-contract tests**

```python
def test_task_branch_is_derived_from_canonical_task_scope() -> None:
    task_id = UUID("11111111-1111-1111-1111-111111111111")

    branch = derive_task_branch(task_id, TaskBranchKind.FEATURE, "bounded-git-workflow")

    assert str(branch) == (
        "feature/11111111-1111-1111-1111-111111111111-bounded-git-workflow"
    )


@pytest.mark.parametrize("slug", ("../escape", "UPPER", "two--hyphens", "main", "x.lock"))
def test_task_branch_rejects_unsafe_slugs(slug: str) -> None:
    with pytest.raises(ValidationError):
        CreateTaskBranchRequest(task_id=uuid4(), kind=TaskBranchKind.FEATURE, slug=slug)


def test_context_and_nested_authority_are_frozen_and_strict() -> None:
    context = git_context()
    with pytest.raises(ValidationError):
        GitWorkflowContext.model_validate({**context.model_dump(), "extra": True}, strict=True)
    with pytest.raises(AttributeError):
        context.actor.permission_ids.add(Permission.NETWORK_ACCESS)
```

- [x] **Step 2: Run Task 1 tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/git_workflow/test_types.py -q
```

Expected: collection fails because `core.git_workflow` does not exist.

- [x] **Step 3: Implement the minimal strict contracts**

Implement `ConfigDict(frozen=True, extra="forbid")` models, exact-type validators for nested
authority/evidence objects, finite fields, tuple/frozenset copying, timezone-aware timestamps, SHA
patterns, safe identifier patterns, and deterministic branch derivation. Model `GitAuthority` with
the persistent agent UUID, canonical `AgentProfile`, and exact permission set; require matching
logical identity and an active profile.

- [x] **Step 4: Run Task 1 tests and verify GREEN**

Run the Task 1 file, then:

```bash
.venv/bin/ruff check core/git_workflow tests/git_workflow
.venv/bin/mypy core/git_workflow tests/git_workflow
```

- [x] **Step 5: Commit Task 1**

```bash
git add core/git_workflow tests/git_workflow
git commit -m "feat(git): define bounded workflow contracts"
```

---

### Task 2: Implement the fixed local Git read boundary

**Files:**

- Create: `core/git_workflow/ports.py`
- Create: `infrastructure/git/__init__.py`
- Create: `infrastructure/git/local.py`
- Create: `tests/git_workflow/git_fixtures.py`
- Create: `tests/git_workflow/test_local_reads.py`
- Create: `tests/git_workflow/test_local_process_safety.py`

**Interfaces:**

- Consumes Task 1 request/result models.
- Produces `GitProvider` protocol methods `status`, `diff`, `history`, `create_task_branch`,
  `commit_changes`, `prepare_pull_request`, and `validate_repository_state`.
- Produces `LocalGitProvider(git_executable: Path, limits: GitProcessLimits)`.
- Internal `_run_git(arguments, workspace, timeout, stdout_limit)` accepts adapter-owned tuples only.

- [x] **Step 1: Write failing real-repository read tests**

```python
def test_status_diff_and_history_are_structured_and_bounded(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")

    provider = local_provider()
    status = asyncio.run(provider.status(repository, timeout_seconds=2.0))
    diff = asyncio.run(
        provider.diff(repository, GitDiffRequest(mode=GitDiffMode.WORKTREE), 2.0)
    )
    history = asyncio.run(provider.history(repository, GitHistoryRequest(limit=10), 2.0))

    assert status.branch == "main"
    assert status.unstaged_count == 1
    assert "-changed" not in diff.patch
    assert "+changed" in diff.patch
    assert history.commits[0].subject == "chore: initialize repository"
```

Add tests for staged and base-branch diffs, safe path filters, detached HEAD, operation-state flags,
history offset/limit, non-UTF-8 output, and explicit truncation.

- [x] **Step 2: Run read tests and verify RED**

Expected: import or missing-method failures for `LocalGitProvider`.

- [x] **Step 3: Implement minimal read commands and parsers**

Use exact fixed argument vectors:

```python
("status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all")
("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames", ...)
("log", "--first-parent", "--format=<NUL-delimited fixed fields>", ...)
```

Resolve path filters with `resolve_workspace_path` and `relative_workspace_path`. Parse into Task 1
models and fail closed on malformed/truncated structured output.

- [x] **Step 4: Write and verify RED process-safety tests**

Tests must prove a recording executable receives only allowlisted flags; host `PATH`,
`GIT_EXTERNAL_DIFF`, `GIT_CONFIG_COUNT`, credentials, askpass, and proxy variables are absent;
timeouts kill the process group; cancellation kills it and raises `CancelledError`; and one request
causes one subprocess invocation.

- [x] **Step 5: Implement process bounds and verify GREEN**

Use `asyncio.create_subprocess_exec`, `stdin=DEVNULL`, bounded concurrent stdout/stderr drains,
`start_new_session=True`, `asyncio.timeout`, terminate-then-kill cleanup, and a literal minimal
environment. Convert all non-cancellation failures to sanitized `GitWorkflowError` values.

- [x] **Step 6: Run focused quality checks and commit Task 2**

```bash
.venv/bin/pytest tests/git_workflow/test_local_reads.py \
  tests/git_workflow/test_local_process_safety.py -q
.venv/bin/ruff check core/git_workflow infrastructure/git tests/git_workflow
.venv/bin/mypy core/git_workflow infrastructure/git tests/git_workflow
git add core/git_workflow infrastructure/git tests/git_workflow
git commit -m "feat(git): add bounded local read provider"
```

---

### Task 3: Add dedicated task-branch mutation

**Files:**

- Modify: `core/git_workflow/ports.py`
- Modify: `infrastructure/git/local.py`
- Create: `core/git_workflow/validation.py`
- Create: `tests/git_workflow/test_branch_creation.py`
- Create: `tests/git_workflow/test_validation.py`

**Interfaces:**

- Consumes `CreateTaskBranchRequest`, `GitWorkflowContext`, and `GitProvider`.
- Produces `validate_write_authority(context) -> None` and canonical branch validation.
- Produces `LocalGitProvider.create_task_branch(...) -> TaskBranchResult`.

- [ ] **Step 1: Write failing authorization and branch-state tests**

```python
def test_developer_creates_exact_task_branch_once(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path)
    request = branch_request(slug="git-workflow")

    result = asyncio.run(local_provider().create_task_branch(repository, request, 2.0))

    assert result.branch == derive_task_branch(request.task_id, request.kind, request.slug)
    assert git(repository, "branch", "--show-current") == str(result.branch)


@pytest.mark.parametrize("state", ("dirty", "detached", "merge", "existing"))
def test_branch_creation_rejects_unsafe_repository_state(tmp_path: Path, state: str) -> None:
    repository = repository_in_state(tmp_path, state)
    with pytest.raises(GitWorkflowError):
        asyncio.run(local_provider().create_task_branch(repository, branch_request(), 2.0))
```

Also prove a Reviewer, missing `git.write`, mismatched task, and protected-head request are rejected
before Git mutation.

- [ ] **Step 2: Run branch tests and verify RED**

Expected: provider method is absent or returns unsupported-operation error.

- [ ] **Step 3: Implement validation and fixed branch creation**

Validate status twice around the mutation, derive the branch internally, call
`git check-ref-format --branch`, reject existing refs with `show-ref --verify --quiet`, then execute
one `switch -c <derived-branch>`. Validate resulting branch and unchanged starting commit.

- [ ] **Step 4: Run focused and regression tests, then commit**

```bash
.venv/bin/pytest tests/git_workflow/test_branch_creation.py \
  tests/git_workflow/test_validation.py tests/tools/test_git_tools.py -q
git add core/git_workflow infrastructure/git tests/git_workflow
git commit -m "feat(git): create isolated task branches"
```

---

### Task 4: Add guarded explicit-path commits

**Files:**

- Create: `infrastructure/git/policy.py`
- Modify: `infrastructure/git/local.py`
- Modify: `core/git_workflow/ports.py`
- Modify: `core/git_workflow/validation.py`
- Create: `tests/git_workflow/test_commit_policy.py`
- Create: `tests/git_workflow/test_commits.py`
- Create: `tests/git_workflow/test_commit_safety.py`

**Interfaces:**

- Produces `GitCommitPolicy.inspect(staged_patch: str) -> CommitPolicyResult`.
- Produces `ObviousSecretCommitPolicy` backed by the existing bounded Phase 18 secret patterns.
- Produces `LocalGitProvider.commit_changes(...) -> GitCommitResult`.

- [ ] **Step 1: Write failing policy and commit tests**

```python
def test_commit_stages_only_explicit_paths_and_uses_conventional_subject(tmp_path: Path) -> None:
    repository, request = task_repository(tmp_path)
    (repository / "selected.txt").write_text("selected\n", encoding="utf-8")
    (repository / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")

    result = asyncio.run(
        local_provider().commit_changes(repository, commit_request(paths=("selected.txt",)), 2.0)
    )

    assert result.subject == "feat(git): add bounded commit"
    assert git(repository, "show", "--format=", "--name-only", "HEAD").strip() == "selected.txt"
    assert "unrelated.txt" in git(repository, "status", "--porcelain")
```

Add RED tests for protected branch, wrong task branch, pre-staged content, empty selection, unsafe
path, symlink escape, empty/truncated patch, obvious secret, failed commit compensation, malicious
summary, hook execution attempt, signing/config inheritance, and unrelated-file preservation.

- [ ] **Step 2: Run commit tests and verify RED**

Expected: commit provider and policy are missing.

- [ ] **Step 3: Implement the minimum policy and commit transaction**

Require clean index; snapshot selected index entries; stage only explicit paths using
`git add --all -- <paths>`; generate a bounded staged patch; reject policy failures; commit once
with a workflow-rendered subject and command-local identity. On failure, restore selected index
entries without changing worktree content. Validate `HEAD` advanced by exactly one non-merge commit
whose subject matches the request.

- [ ] **Step 4: Run commit, security-redaction, and Git regression tests**

```bash
.venv/bin/pytest tests/git_workflow/test_commit_policy.py \
  tests/git_workflow/test_commits.py tests/git_workflow/test_commit_safety.py \
  tests/security/test_redaction.py tests/tools/test_git_tools.py -q
```

- [ ] **Step 5: Commit Task 4**

```bash
git add core/git_workflow infrastructure/git tests/git_workflow
git commit -m "feat(git): commit explicit paths safely"
```

---

### Task 5: Add append-only Git operation auditing

**Files:**

- Create: `core/git_workflow/audit.py`
- Create: `infrastructure/git/audit.py`
- Create: `tests/git_workflow/test_audit_types.py`
- Create: `tests/database/test_git_workflow_audit.py`

**Interfaces:**

- Produces `GitAuditRecord` with exact scalar allowlist and `GitAuditRecorder.record(record) -> None`.
- Produces `SQLAlchemyGitAuditRecorder(session: Session)` backed by `AuditEvent`.
- Uses `GIT_OPERATION_STARTED`, `GIT_OPERATION_COMPLETED`, and `GIT_OPERATION_FAILED` event types.

- [ ] **Step 1: Write failing strict audit-contract tests**

Prove raw path/diff/subject/error keys are rejected, nested values are rejected, non-finite numeric
values are rejected, and copied data becomes immutable.

- [ ] **Step 2: Run audit-contract tests and verify RED**

Expected: `GitAuditRecord` and recorder do not exist.

- [ ] **Step 3: Implement immutable audit contract and SQLAlchemy recorder**

Map the trusted context to `AuditEvent(actor_type=AGENT, resource_type="GIT_REPOSITORY")`, validate
the persistent project/task/agent/run scope, append and flush exactly one event, sanitize all
persistence failures to `AUDIT_FAILED`, and never commit or close the caller-owned session.

- [ ] **Step 4: Write and run real-PostgreSQL audit tests**

```python
def test_git_audit_is_append_only_and_metadata_only(db_session: Session) -> None:
    scope = persisted_git_scope(db_session)
    recorder = SQLAlchemyGitAuditRecorder(db_session)
    recorder.record(started_git_record(scope))
    db_session.commit()

    event = db_session.scalar(select(AuditEvent).where(AuditEvent.task_id == scope.task_id))
    assert event is not None
    assert set(event.data) <= GIT_AUDIT_DATA_KEYS
    with pytest.raises(AppendOnlyViolationError):
        event.action = "forged"
        db_session.flush()
```

Run with `TEST_POSTGRES_PORT=55433` and verify Alembic creates the schema.

- [ ] **Step 5: Commit Task 5**

```bash
git add core/git_workflow infrastructure/git tests/git_workflow \
  tests/database/test_git_workflow_audit.py
git commit -m "feat(git): audit workflow operations"
```

---

### Task 6: Orchestrate audited Git operations

**Files:**

- Create: `core/git_workflow/workflow.py`
- Modify: `core/git_workflow/__init__.py`
- Create: `tests/git_workflow/fakes.py`
- Create: `tests/git_workflow/test_workflow.py`
- Create: `tests/git_workflow/test_workflow_safety.py`

**Interfaces:**

- Produces `GitWorkflow(provider, audit_recorder, commit_policy, lock_registry)`.
- Exposes async `create_task_branch`, `commit_changes`, `get_status`, `get_diff`, `get_history`,
  `prepare_pull_request`, and `validate_merge_requirements`.
- Serializes all operations per canonical workspace and never closes injected resources.

- [ ] **Step 1: Write failing operation-order and audit tests**

```python
def test_started_audit_precedes_one_provider_call_and_completed_audit() -> None:
    provider = RecordingGitProvider(status_result=clean_status())
    audit = RecordingGitAuditRecorder()
    workflow = GitWorkflow(provider=provider, audit_recorder=audit, ...)

    asyncio.run(workflow.get_status(git_context()))

    assert audit.timeline == ["STARTED", "PROVIDER", "COMPLETED"]
    assert provider.status_calls == 1
```

Add tests that start-audit failure prevents Git, provider failure records one sanitized failure,
terminal-audit failure does not retry Git, cancellation leaves only start audit, timeout is passed
once, injected resources are not closed, and concurrent operations for one workspace serialize.

- [ ] **Step 2: Run workflow tests and verify RED**

Expected: `GitWorkflow` does not exist.

- [ ] **Step 3: Implement the minimal orchestration template**

Implement one private `_execute` path that validates exact request/context types, acquires the
workspace lock, records start, invokes one provider operation under the remaining deadline, records
completed or failed metadata, and clears operation-local references in `finally`. Re-raise
`CancelledError` immediately after provider cleanup without terminal audit.

- [ ] **Step 4: Verify workflow tests and commit**

```bash
.venv/bin/pytest tests/git_workflow/test_workflow.py \
  tests/git_workflow/test_workflow_safety.py -q
git add core/git_workflow tests/git_workflow
git commit -m "feat(git): orchestrate audited operations"
```

---

### Task 7: Prepare local pull requests and validate merge requirements

**Files:**

- Modify: `core/git_workflow/types.py`
- Modify: `core/git_workflow/ports.py`
- Modify: `core/git_workflow/validation.py`
- Modify: `core/git_workflow/workflow.py`
- Modify: `infrastructure/git/local.py`
- Create: `tests/git_workflow/test_pull_request_preparation.py`
- Create: `tests/git_workflow/test_merge_validation.py`

**Interfaces:**

- Produces stable `PullRequestPreparation.checksum` from canonical JSON fields.
- Produces read-only `MergeValidationResult(decision=PASS|BLOCK, reason_codes=...)`.
- Does not create `PullRequest`, `Approval`, remote requests, or Git merges.

- [ ] **Step 1: Write failing preparation tests**

```python
def test_prepare_pull_request_returns_stable_local_metadata(tmp_path: Path) -> None:
    repository, context = committed_task_repository(tmp_path)

    preparation = asyncio.run(workflow(repository).prepare_pull_request(context, request()))

    assert preparation.base_branch == "main"
    assert preparation.head_branch.startswith("feature/")
    assert preparation.commit_count == 1
    assert preparation.changed_paths == ("tracked.txt",)
    assert len(preparation.checksum) == 64
    assert git(repository, "remote") == ""
```

Also reject dirty state, no commits, non-ancestor base, merge commits, protected head, stale task
branch, and truncated diff/history.

- [ ] **Step 2: Run preparation tests and verify RED, then implement GREEN**

Use fixed local commands (`merge-base --is-ancestor`, `rev-list --count`, `diff --numstat`,
`diff --name-only`) with bounded parsers. Generate title and summary from safe typed fields and hash
canonical JSON with SHA-256.

- [ ] **Step 3: Write failing deterministic merge-gate tests**

```python
def test_merge_requirements_pass_only_for_fresh_independent_verified_scope() -> None:
    result = asyncio.run(
        workflow.validate_merge_requirements(
            context,
            merge_request(
                reviewer_id="reviewer-agent-01",
                reviewer_status=GitCheckStatus.PASS,
                qa_status=GitCheckStatus.PASS,
                security_status=GitCheckStatus.PASS,
            ),
        )
    )

    assert result.decision is MergeDecision.PASS
    assert result.reason_codes == ()
```

Add literal expected reason-code tests for author equals reviewer, missing/failed/truncated checks,
stale SHA/checksum, wrong correlation/project/task, dirty state, protected head, changed base,
non-ancestor history, and merge commits. Prove all failures return `BLOCK` and never mutate refs.

- [ ] **Step 4: Implement merge validation and verify GREEN**

Validate immutable evidence first, then repository state. Accumulate only stable reason codes in a
deterministic order. Never return raw Git output or invoke commit, switch, merge, push, or fetch.

- [ ] **Step 5: Run all Phase 19 tests and commit Task 7**

```bash
TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/git_workflow \
  tests/database/test_git_workflow_audit.py -q
git add core/git_workflow infrastructure/git tests/git_workflow
git commit -m "feat(git): prepare and validate merge handoffs"
```

---

### Task 8: Integrate, document, and verify Phase 19

**Files:**

- Create: `docs/git-workflow.md`
- Create: `docs/adr/0012-provider-neutral-local-git-workflow.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`
- Modify: `docs/superpowers/plans/2026-09-08-phase-19-git-workflow.md`
- Create: `tests/git_workflow/test_integration.py`

**Interfaces:**

- Provides one real local-Git plus real-PostgreSQL integration path.
- Documents exact safety guarantees and Phase 20 exclusions.
- Marks only verified Phase 19 checklist boxes.

- [ ] **Step 1: Write failing end-to-end integration test**

The test provisions persistent Project, Task, Agent, and AgentRun records; creates a real temporary
Git repository; creates the task branch through `GitWorkflow`; commits one explicit path; reads
status/diff/history; prepares the local PR record; validates independent Reviewer/QA/Security
evidence; commits the SQLAlchemy session; and asserts ordered metadata-only append-only audit events.

- [ ] **Step 2: Run the integration test and verify RED**

Expected: fail on the first missing composition or persistence behavior not yet connected.

- [ ] **Step 3: Complete composition and make integration GREEN**

Add only exports or small composition helpers necessary for the tested Phase 19 path. Do not add an
API route, remote provider, database migration, or Phase 20 model.

- [ ] **Step 4: Write documentation and update only Phase 19 checklist boxes**

Document architecture, operation matrix, branch/commit conventions, audit allowlist, process
security, known process-local locking limitation, and explicit future remote-provider boundary.
Update repository status to Phase 19 completed and Phase 20 unimplemented.

- [ ] **Step 5: Run complete verification**

```bash
TEST_POSTGRES_PORT=55433 make test
make lint
make typecheck
.venv/bin/ruff format --check .
git diff --check origin/main
```

Expected: zero test failures, zero Ruff findings, zero mypy errors, all files formatted, and no
whitespace errors.

- [ ] **Step 6: Perform focused security and scope review**

Verify no command path includes `push`, `fetch`, `merge`, `reset --hard`, `clean`, `stash`, arbitrary
`-c` configuration, shell execution, or remote URLs; no audit data includes raw paths/diffs/errors;
and no Phase 20 checkbox or behavior changed. Correct every Critical or Important finding and rerun
the complete gate.

- [ ] **Step 7: Mark this plan complete and commit**

```bash
git add docs README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md tests/git_workflow
git commit -m "docs(git): complete Phase 19 delivery"
```

- [ ] **Step 8: Push and open the Phase 19 pull request**

Push `phase-19/git-workflow`, create a PR targeting `main`, and preserve the worktree for review.
