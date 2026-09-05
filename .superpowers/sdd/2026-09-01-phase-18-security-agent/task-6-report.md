# Task 6 Report — Persistent Security workflow contracts and preflight

## Status and scope

Status: complete. The implementation source was originally committed at
`2302270a5c428b61f7ede0beef27564f3352c8da`; this expanded report is included by a report-only
amend. The implementation adds strict immutable workflow request/result contracts,
leak-resistant errors, the `SecurityRunner` port, and a caller-owned-session persistent preflight.
The preflight row-locks the task, loads four persistent agents, enforces exact active roles and
independence, preserves Developer assignment, authenticates task/project/text/correlation and
managed-workspace path scope, requires successful QA/test evidence, and validates Security
authority. It does not commit, close the session, or invoke a Security runner.

## TDD evidence

The required initial RED was run before any Task 6 production module existed:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_types.py tests/workflows/test_security_validation.py -q
ImportError: cannot import name 'SecurityWorkflowOutcome' from 'core.workflows'
ImportError: cannot import name 'SecurityWorkflowError' from 'core.workflows'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
```

Exit status was 2. This was the expected RED because both test modules reached the public workflow
boundary and failed specifically on the missing Task 6 exports, not on a typo or an unrelated test.

After the minimal implementation, the same focused command was first attempted in the sandbox.
The 13 contract tests passed, while PostgreSQL setup was blocked with
`OperationalError: ... port 55433 failed: Operation not permitted`; this was a sandbox TCP block,
not a product failure. The approved external rerun used the same dedicated port and passed:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_types.py tests/workflows/test_security_validation.py -q
..............................................................           [100%]
```

The first required QA regression run also passed:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_types.py tests/workflows/test_security_validation.py tests/workflows/test_qa_validation.py -q
........................................................................ [ 80%]
.................                                                        [100%]
```

Self-review added two adversarial tests through their own RED/GREEN cycles. Exact UUID enforcement
first failed because a fully string-forged scope returned `INTERNAL_FAILURE` rather than
`INVALID_INPUT`:

```text
$ .venv/bin/pytest tests/workflows/test_security_validation.py::test_security_preflight_rejects_forged_non_uuid_scope_before_persistence -q
FAILED tests/workflows/test_security_validation.py::test_security_preflight_rejects_forged_non_uuid_scope_before_persistence
E AssertionError: assert <SecurityWorkflowErrorCode.INTERNAL_FAILURE: 'INTERNAL_FAILURE'> is <SecurityWorkflowErrorCode.INVALID_INPUT: 'INVALID_INPUT'>
```

After requiring exact UUID objects before session access, the exact command returned:

```text
.                                                                        [100%]
```

The declared-tool scope classification test initially failed as expected. The first unquoted node
ID attempt was rejected by zsh as a glob (`zsh:1: no matches found`) and was not counted as RED.
The corrected quoted command exercised the code and exposed the intended mismatch:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest 'tests/workflows/test_security_validation.py::test_security_preflight_rejects_execution_context_mismatch[tools]' -q
FAILED tests/workflows/test_security_validation.py::test_security_preflight_rejects_execution_context_mismatch[tools]
E AssertionError: assert <SecurityWorkflowErrorCode.INVALID_AGENT: 'INVALID_AGENT'> is <SecurityWorkflowErrorCode.INVALID_SCOPE: 'INVALID_SCOPE'>
```

After preserving nested Security error classification, that exact command returned:

```text
.                                                                        [100%]
```

The final focused Task 6 plus QA regression run passed 91 tests:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_types.py tests/workflows/test_security_validation.py tests/workflows/test_qa_validation.py -q
........................................................................ [ 79%]
...................                                                      [100%]
```

## Final verification evidence

Full Alembic-backed PostgreSQL suite on the dedicated port:

```text
$ TEST_POSTGRES_PORT=55433 make test
.venv/bin/pytest
........................................................................ [  4%]
........................................................................ [  8%]
........................................................................ [ 13%]
........................................................................ [ 17%]
........................................................................ [ 21%]
........................................................................ [ 26%]
........................................................................ [ 30%]
........................................................................ [ 34%]
........................................................................ [ 39%]
........................................................................ [ 43%]
........................................................................ [ 47%]
........................................................................ [ 52%]
........................................................................ [ 56%]
........................................................................ [ 60%]
........................................................................ [ 65%]
........................................................................ [ 69%]
........................................................................ [ 73%]
........................................................................ [ 78%]
........................................................................ [ 82%]
........................................................................ [ 86%]
........................................................................ [ 91%]
........................................................................ [ 95%]
........................................................................ [ 99%]
...                                                                      [100%]
1659 passed in 10.82s
```

Ruff:

```text
$ make lint
.venv/bin/ruff check .
All checks passed!
```

mypy:

```text
$ make typecheck
.venv/bin/mypy .
Success: no issues found in 306 source files
```

Formatting was applied only to the eight owned Python files:

```text
$ .venv/bin/ruff format core/workflows/security_types.py core/workflows/security_errors.py core/workflows/security_ports.py core/workflows/security_validation.py core/workflows/__init__.py tests/workflows/security_factories.py tests/workflows/test_security_types.py tests/workflows/test_security_validation.py
2 files reformatted, 6 files left unchanged
```

An earlier format check returned `8 files already formatted`; the final formatting command above
was rerun after the last TDD correction. `git diff --check`, `git diff --cached --check`, and
`git diff HEAD^ --check` each exited 0 with no output.

## Files changed

- `.superpowers/sdd/2026-09-01-phase-18-security-agent/task-6-report.md`
- `core/workflows/__init__.py`
- `core/workflows/security_errors.py`
- `core/workflows/security_ports.py`
- `core/workflows/security_types.py`
- `core/workflows/security_validation.py`
- `tests/workflows/security_factories.py`
- `tests/workflows/test_security_types.py`
- `tests/workflows/test_security_validation.py`

No other file was changed. The untracked `.venv` was preserved and excluded from staging.

## Self-review and concerns

- Raw nested exact types, including immutable capability declarations, are checked before any
  serialization can normalize a forged `model_copy` value.
- Four persistent UUIDs and four nested slugs must be distinct; persisted roles are exactly
  Developer, Reviewer, QA, and Security; Developer remains the task assignee; task state is exactly
  `WAITING_SECURITY`.
- Managed source paths must be canonical existing regular files under a `projects/<project UUID>`
  workspace and match both old/new diff headers. A test deliberately changes workspace file bytes
  and confirms validation still accepts the request: caller-supplied source bytes are bounded but
  are not falsely represented as database-authenticated.
- Every rejection test checks unchanged task state/assignment, unchanged audit count, no runner
  invocation, and a still caller-owned active session transaction.
- No blocking concern remains. The source-byte limitation above is deliberate and documented;
  Task 6 performs preflight only and does not add Task 7 orchestration, audits, or transitions.
- No MCP evidence was claimed and no subagent was used.
