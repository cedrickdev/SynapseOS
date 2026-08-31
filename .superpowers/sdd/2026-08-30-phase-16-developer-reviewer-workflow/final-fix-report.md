# Phase 16 Developer–Reviewer Workflow Final Fix Report

Date: 2026-08-31
Branch: `phase-16/developer-reviewer-workflow`
Reviewed range: `bfb2dcc..2709019`
Requested commit: `fix(workflow): close Phase 16 safety gaps`

## Outcome

All seven final-review findings are fixed in one wave. The implementation preserves caller-owned
resources, bounded data, exact correlation, append-only audit history, and the Phase 16-only scope.
No retry, fallback, QA, Security, generic workflow engine, Phase 17 work, migration, or schema
change was introduced.

The resumed partial-state baseline passed before further edits:

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows tests/reviewer tests/tasks \
  tests/database/test_task_state_machine.py tests/database/test_append_only.py -q
Result: exit 0
```

Local PostgreSQL access was unavailable inside the filesystem sandbox, so PostgreSQL-backed test
commands were rerun with the existing local-database permission. No test was replaced by an
in-memory database, `create_all`, or a mock persistence substitute.

## Finding 1 — stale task overwrite

### RED

The new independent-session race test used real PostgreSQL and
`sessionmaker(expire_on_commit=False)`. One case moved the task to `WAITING_HUMAN` during the
Developer call; the other moved it to `CANCELLED` during the Reviewer call.

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows/test_safety.py -q \
  -k concurrent_human_transition_wins
Result: FF; 2 failed
Failure: both stale workflow checkpoints completed instead of raising WorkflowError.
```

### Design and implementation

- Every checkpoint now starts a transaction, installs its database deadline when supplied, and
  reloads the task with `SELECT ... FOR UPDATE` plus `populate_existing=True` under
  `session.no_autoflush`.
- Every checkpoint declares its exact expected source status and assigned Developer UUID.
  Assignment alone expects `READY` with no assignee.
- The locked row is verified before snapshotting, staging a transition, or staging an audit fact.
- The orchestrator tracks the last committed status and supplies it to safe escalation.
- A lock/reload mismatch is `INVALID_STATE`. The orchestrator does not attempt a stale
  `WAITING_HUMAN` escalation for that category, so the concurrent human/cancel state wins without
  an overwrite or audit lie.
- Checkpoint commits still occur before each external collaborator call, so no transaction or row
  lock is held across Developer, handoff-builder, or Reviewer execution.

### GREEN

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows/test_safety.py -q \
  -k concurrent_human_transition_wins
Result: ..; 2 passed
```

The existing stale-assignment, state-machine, append-only, and checkpoint chronology tests also
remain green.

## Finding 2 — sensitive traceback retention

### RED

Focused tests placed reachable markers in task text, workspace/profile data, diff content,
Developer report content, and request/session scope. They traversed the public
`WorkflowError` traceback frames and reachable objects.

```text
.venv/bin/pytest \
  tests/workflows/test_validation.py::test_direct_validation_failure_traceback_does_not_retain_workflow_scope \
  tests/workflows/test_handoff.py::test_direct_handoff_failure_traceback_does_not_retain_evidence_scope \
  tests/workflows/test_safety.py::test_orchestrator_preflight_failure_traceback_does_not_retain_workflow_scope \
  -q
Result: FFF; 3 failed
Failure: public traceback frames retained request/evidence/session scope.
```

### Design and implementation

- Workflow request validation and handoff validation now have internal result-or-error paths.
- All caught failures recursively detach traceback, cause, and context links and clear traceback
  frames before the stable code leaves the internal path.
- Direct public wrappers delete request, session, context, result, diff/report/profile, and other
  sensitive arguments before calling a tiny scope-free raising helper.
- The orchestrator performs preflight through the result-or-error path and clears all sensitive
  run locals before its final public raise.
- Public errors expose only the closed `WorkflowErrorCode` and its existing stable safe message;
  raw exception messages never reach audit data or the caller.

### GREEN

```text
.venv/bin/pytest \
  tests/workflows/test_validation.py::test_direct_validation_failure_traceback_does_not_retain_workflow_scope \
  tests/workflows/test_handoff.py::test_direct_handoff_failure_traceback_does_not_retain_evidence_scope \
  tests/workflows/test_safety.py::test_orchestrator_preflight_failure_traceback_does_not_retain_workflow_scope \
  -q
Result: ...; 3 passed
```

## Finding 3 — Reviewer authority was validated too late

### RED

```text
.venv/bin/pytest \
  tests/reviewer/test_validation.py::test_profile_authority_validator_reuses_reviewer_read_only_rules \
  tests/workflows/test_safety.py::test_reviewer_authority_is_rejected_before_workflow_side_effects \
  -q
Result: collection error
Failure: validate_reviewer_profile_authority was not available.
```

### Design and implementation

- `validate_reviewer_profile_authority` was extracted from the Reviewer request validator and is
  reused by both direct Reviewer validation and workflow preflight.
- It exact-type checks and canonicalizes the complete `AgentProfile`, then enforces Reviewer role,
  active status, required filesystem read access, the read-only permission allowlist, and the
  Reviewer tool allowlist.
- Workflow preflight maps unsafe Reviewer authority to the stable `INVALID_AGENT` workflow code.
- This validation completes before assignment, audit, Developer execution, handoff construction,
  or Reviewer execution.
- The existing Reviewer request validation contract and immutable canonical permission result are
  preserved.

### GREEN

```text
.venv/bin/pytest \
  tests/reviewer/test_validation.py::test_profile_authority_validator_reuses_reviewer_read_only_rules \
  tests/workflows/test_safety.py::test_reviewer_authority_is_rejected_before_workflow_side_effects \
  -q
Result: ....; 4 passed parameter cases
```

## Finding 4 — Developer output canonicalization

### RED

```text
.venv/bin/pytest \
  tests/workflows/test_safety.py::test_malformed_developer_result_is_rejected_before_waiting_review_or_handoff \
  -q
Result: F; 1 failed
Failure: malformed output reached later handoff validation and surfaced as UNSAFE_HANDOFF instead
of failing at the collaborator boundary.
```

### Design and implementation

- Developer output is now exact-type checked and fully round-trip canonicalized as a complete
  `DeveloperResult` inside `_invoke_collaborator` immediately after the Developer returns.
- Canonicalization occurs before `commit_developer_completed_checkpoint`, before the task can
  enter `WAITING_REVIEW`, and before the handoff builder is called.
- Type-confused or malformed nested evidence maps to safe `COLLABORATOR_FAILURE`; the existing
  safe checkpoint moves the still-`IN_PROGRESS` task to `WAITING_HUMAN` exactly once.

### GREEN

```text
.venv/bin/pytest \
  tests/workflows/test_safety.py::test_malformed_developer_result_is_rejected_before_waiting_review_or_handoff \
  -q
Result: .; 1 passed
```

## Finding 5 — rollback ownership

### RED

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest \
  tests/workflows/test_audit.py::test_rollback_failure_invalidates_only_the_poisoned_connection_and_session_cannot_commit \
  -q
Result: F; 1 failed
Failure: caller-owned Session.invalidate was called once.
```

### Design and implementation

- The active SQLAlchemy `Connection` is captured before checkpoint work starts.
- If and only if rollback itself fails, recovery invalidates that poisoned connection. It never
  calls `Session.invalidate()` or `Session.close()`.
- The result remains fatal `PERSISTENCE_FAILURE`; rollback-failure safety was not downgraded.
- Best-effort task snapshot restoration and task-status authorization cleanup remain in place.
- The regression proves the poisoned caller Session cannot later commit partial checkpoint state,
  while a fresh Session observes the original task and no false workflow audit fact.

### GREEN

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest \
  tests/workflows/test_audit.py::test_rollback_failure_invalidates_only_the_poisoned_connection_and_session_cannot_commit \
  -q
Result: .; 1 passed
```

## Finding 6 — whole-workflow timeout

### RED

The preflight case performs a real PostgreSQL `pg_sleep`; the checkpoint case uses an independent
thread/session to hold a real task-row `SELECT FOR UPDATE` lock.

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest \
  tests/workflows/test_safety.py::test_global_deadline_times_out_blocked_preflight_sql_before_assignment \
  tests/workflows/test_safety.py::test_global_deadline_times_out_a_blocked_checkpoint_row_lock_without_retry \
  -q
Result: FF; 2 failed
Failure: neither blocked synchronous SQL path raised within the requested workflow timeout.
```

### Design and implementation

- The request timeout remains exact, finite, positive, and capped at 3,600 seconds.
- One monotonic work deadline is computed before preflight, and preflight, normal checkpoints, and
  collaborator calls run inside the outer `asyncio.timeout` scope.
- Immediately before preflight persistence and every checkpoint, the remaining deadline is
  installed with PostgreSQL transaction-local `statement_timeout` and `lock_timeout` settings.
- SQLSTATE `57014` (query cancellation) and `55P03` (lock timeout) map to stable `TIMEOUT`.
- Timeout settings end with their checkpoint commit or rollback and are never held across an
  external call.
- Preflight timeout rolls back its transaction and has zero assignment/audit/collaborator effects.
- A timeout after workflow start uses the existing fail-closed escalation path without retry or an
  extra collaborator call. After the work deadline, only that persistence cleanup receives a
  separate maximum 50-millisecond transaction budget.

### GREEN

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest \
  tests/workflows/test_safety.py::test_global_deadline_times_out_blocked_preflight_sql_before_assignment \
  tests/workflows/test_safety.py::test_global_deadline_times_out_a_blocked_checkpoint_row_lock_without_retry \
  -q
Result: ..; 2 passed
```

The pre-existing collaborator timeout and cancellation tests also remain green and prove no retry
or post-cancellation call.

## Finding 7 — false public audit facts

### RED

```text
.venv/bin/pytest \
  tests/workflows/test_audit.py::test_raw_workflow_event_staging_is_not_publicly_exposed -q
Result: F; 1 failed
Failure: core.workflows still exposed append_workflow_event.
```

### Design and implementation

- Raw event staging is now the private `_stage_workflow_event` implementation and is absent from
  `core.workflows` imports and `__all__`.
- Public workflow audit entry points are state-coupled checkpoint functions. Each locks and
  verifies the legal source task state and assigned Developer before it can stage an event.
- Audit tests now drive assignment, handoff, review, exhaustion, completion, and safe failure
  facts through legal checkpoint/state sequences, while continuing to assert the bounded scalar
  allowlist and append-only protection.
- There is no public path that can append `WORKFLOW_COMPLETED` to a `READY` task.

### GREEN

```text
.venv/bin/pytest \
  tests/workflows/test_audit.py::test_raw_workflow_event_staging_is_not_publicly_exposed -q
Result: .; 1 passed
```

The complete workflow audit suite passed as part of the focused and full gates.

## Verification

Focused Phase 16 workflow suite:

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows -q
Result: exit 0
```

Focused workflow, Reviewer, task-state, and database safety suites:

```text
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows tests/reviewer tests/tasks \
  tests/database/test_task_state_machine.py tests/database/test_append_only.py -q
Result: exit 0; 435 tests passed
```

Focused static checks:

```text
.venv/bin/ruff check core/workflows core/reviewer tests/workflows tests/reviewer
All checks passed!

.venv/bin/ruff format --check core/workflows core/reviewer tests/workflows tests/reviewer
38 files already formatted

.venv/bin/mypy core/workflows core/reviewer tests/workflows tests/reviewer
Success: no issues found in 38 source files
```

Final repository gate:

```text
TEST_POSTGRES_PORT=55432 make check
.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy .
Success: no issues found in 242 source files
.venv/bin/pytest
1174 passed in 9.12s
Result: exit 0
```

Final formatting and diff hygiene:

```text
.venv/bin/ruff format --check .
306 files already formatted

git diff --check
Result: exit 0; no output

git diff --cached --check
Result: exit 0; no output
```

## Files

Production:

- `core/reviewer/__init__.py`
- `core/reviewer/validation.py`
- `core/workflows/__init__.py`
- `core/workflows/audit.py`
- `core/workflows/deadline.py`
- `core/workflows/errors.py`
- `core/workflows/handoff.py`
- `core/workflows/orchestrator.py`
- `core/workflows/validation.py`

Tests:

- `tests/reviewer/test_validation.py`
- `tests/workflows/test_audit.py`
- `tests/workflows/test_handoff.py`
- `tests/workflows/test_safety.py`
- `tests/workflows/test_validation.py`
- `tests/workflows/traceback_assertions.py`

Documentation:

- `docs/developer-reviewer-workflow.md`
- `.superpowers/sdd/2026-08-30-phase-16-developer-reviewer-workflow/final-fix-report.md`

## Self-review and concerns

- Stale `expire_on_commit=False` identity-map state cannot bypass any workflow checkpoint.
- `INVALID_STATE` from a concurrent human/cancel transition cannot trigger a second stale
  escalation attempt.
- Reviewer write/command authority is rejected before every workflow side effect.
- Malformed Developer output cannot reach `WAITING_REVIEW` or handoff construction.
- No checkpoint closes or invalidates the caller Session; a rollback-failed Session remains fatal
  and caller-managed.
- The normal workflow uses one deadline from before preflight. The only separate budget is the
  documented, persistence-only, maximum 50-millisecond safe-failure cleanup after work timeout;
  it cannot call or retry a collaborator.
- Raw audit staging is private and completion facts are tied to the approving state transition.
- No known unresolved correctness, safety, typing, formatting, migration, or test concern remains.
- `CLAUDE.local.md` was not read, changed, staged, or included.
