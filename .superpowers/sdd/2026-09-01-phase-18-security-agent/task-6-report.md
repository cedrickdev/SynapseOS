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

## Fix round 1/5 — four Important review findings

The inherited uncommitted RED edits in `tests/workflows/security_factories.py` and
`tests/workflows/test_security_validation.py` were preserved and completed. No subagent was used.

### RED evidence

The first sandbox run could execute the three persistence-free cases, but local TCP access to the
dedicated PostgreSQL instance was denied. Those database setup errors were environmental and were
not counted as product RED. The same command was rerun with approved local PostgreSQL access:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_validation.py -q
.FFF..FF................................FFFFFF.................          [100%]
11 failed
```

The failures matched the four findings:

- three malformed nested scalars returned `INTERNAL_FAILURE` after persistence access was
  attempted instead of failing canonicalization as `INVALID_INPUT` before database access;
- a forged string workspace root was consumed before reconstruction and returned `INVALID_SCOPE`;
- the valid nullable-description fixture failed because canonical `""` was not representable by
  `SecurityRequest.task_description`;
- forged `name`, `department`, `seniority`, allowed autonomy level, reputation score, and
  reliability score were accepted instead of being authenticated against the persisted Security
  agent.

The inherited lifecycle instrumentation and public-boundary assertion already passed in this RED
run: the validator exposes only `(session, request)`, and patched caller-session `commit` and
`close` methods were not called.

### GREEN implementation and evidence

Raw exact-type and mutable-capability guards now run first. The request is then reconstructed
immediately, and only that canonical `SecurityWorkflowRequest` is used for persistence lookup,
task/profile/QA/context checks, and managed-filesystem validation. Schema-invalid forged QA or
correlation combinations consequently fail as `INVALID_INPUT` before persistence; canonical scope
mismatches retain their existing workflow-specific classifications.

The complete persisted Security profile is authenticated: slug-backed profile ID, name, role,
department, seniority, status, autonomy level, reputation score, and reliability score. Both
scores are converted explicitly through finite `Decimal` values before comparison. The workflow
fixture derives those score declarations from the persisted row rather than relying on matching
defaults.

Nullable persisted task descriptions are compared as `task.description or ""`. To make that
canonical value representable without relaxing any other Security text field,
`SecurityRequest.task_description` alone now accepts a bounded empty string. The real-PostgreSQL
regression proves a valid `NULL` task description returns canonical `""`.

Scope clarification: `core/security/types.py` is not involved in persisted profile score
authentication and is not necessary for that finding. Score authentication is implemented wholly
inside `core/workflows/security_validation.py`, where both persisted scores are converted to finite
canonical `Decimal` values before comparison. The cross-scope Security type edit is retained only
because it is strictly necessary for the separate required nullable-description finding: the
workflow contract revalidates its nested `SecurityRequest`, and the prior nonblank field constraint
made canonical `task.description or ""` impossible to represent.

This necessity was verified with a controlled mutation check. Temporarily restoring the prior
nonblank `SecurityRequest.task_description` constraint produced:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_validation.py -q -k 'nullable_persistent_description or reputation_score or reliability_score'
F..                                                                      [100%]
```

Both forged persisted-score mismatch regressions remained green, directly proving the Security
type edit is unnecessary for profile score authentication. Only the valid PostgreSQL
NULL-description regression failed, at `SecurityRequest` construction with
`task_description: String should have at least 1 character`. The committed bounded-empty field
constraint was then restored. A Task 6-only bypass would require constructing a nested request that
fails its own public schema revalidation, contradicting the requirement to use a canonical
`SecurityWorkflowRequest`; that workaround was therefore not used.

The disconnected runner double was removed. Rejection and acceptance paths directly instrument
the caller-owned SQLAlchemy session so any `commit()` or `close()` call fails immediately, while
the existing task-state, assignment, audit-count, and active-transaction assertions remain. A
public API-boundary test proves the validator accepts no collaborator/runner parameter, so
collaborator execution is structurally outside this preflight function.

Focused Security validation:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_validation.py -q
...............................................................          [100%]
```

Focused Task 6 plus QA regression validation:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/workflows/test_security_types.py tests/workflows/test_security_validation.py tests/workflows/test_qa_validation.py -q
........................................................................ [ 69%]
...............................                                          [100%]
```

The complete Security and workflow test areas also passed:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/security tests/workflows -q
........................................................................ [ 15%]
........................................................................ [ 30%]
........................................................................ [ 45%]
........................................................................ [ 60%]
........................................................................ [ 75%]
........................................................................ [ 90%]
..............................................                           [100%]
```

Fresh repository-wide verification on the dedicated PostgreSQL port passed:

```text
$ TEST_POSTGRES_PORT=55433 make test
1671 passed in 11.50s

$ make lint
All checks passed!

$ make typecheck
Success: no issues found in 306 source files

$ .venv/bin/ruff format --check core/security/types.py core/workflows/security_validation.py tests/workflows/security_factories.py tests/workflows/test_security_validation.py
4 files already formatted

$ git diff --check
(no output; exit 0)
```

The deferred `exact_type_check` typing Minor was intentionally not addressed. The untracked
`.venv` remained preserved and excluded from staging.

## Fix round 2/5 — reject whitespace-only Security task descriptions

Scoped re-review found that the fix-round-1 `TaskDescription8192` constraint allowed any string up
to 8,192 characters, including whitespace-only text. The required contract is exactly empty text
for a nullable persisted description, or bounded text containing at least one non-whitespace
character.

Two direct `SecurityRequest` contract regressions were added before production changes: one keeps
the canonical empty-string case accepted, and one rejects the literal `" \t\n"`. The focused RED
was:

```text
$ .venv/bin/pytest tests/security/test_types.py -q -k 'task_description'
.F                                                                       [100%]
FAILED tests/security/test_types.py::test_request_rejects_whitespace_only_task_description
E Failed: DID NOT RAISE ValidationError
```

The passing empty-description case in the same RED run proved that the prior nullable-description
fix remained intact. The production correction was limited to a conditional after-validator on
`TaskDescription8192`: exactly `""` is returned unchanged, while every non-empty value reuses the
existing nonblank validation. The same focused command then passed:

```text
$ .venv/bin/pytest tests/security/test_types.py -q -k 'task_description'
..                                                                       [100%]
```

Focused Security type plus real-PostgreSQL Task 6 workflow validation passed:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/security/test_types.py tests/workflows/test_security_validation.py -q
........................................................................ [ 64%]
.......................................                                  [100%]
```

The complete Security and workflow regression areas passed:

```text
$ TEST_POSTGRES_PORT=55433 .venv/bin/pytest tests/security tests/workflows -q
........................................................................ [ 15%]
........................................................................ [ 30%]
........................................................................ [ 45%]
........................................................................ [ 60%]
........................................................................ [ 75%]
........................................................................ [ 90%]
................................................                         [100%]
```

Fresh static and formatting verification:

```text
$ .venv/bin/ruff format core/security/types.py tests/security/test_types.py
2 files left unchanged

$ make lint
All checks passed!

$ make typecheck
Success: no issues found in 306 source files

$ .venv/bin/ruff format --check core/security/types.py tests/security/test_types.py
2 files already formatted

$ git diff --check
(no output; exit 0)
```

No subagent was used. Prior Task 6 fixes and the untracked `.venv` were preserved. Deferred
unrelated Minors, including `exact_type_check` typing, were not addressed.
