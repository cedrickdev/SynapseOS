# Phase 17 QA Agent Design

## Scope

Phase 17 introduces one independent `QAAgent` and one focused QA workflow stage. The agent receives
the approved review evidence, bounded task and repository context, acceptance criteria, existing
check evidence, and a closed list of test profiles. It executes the required test profiles through
the existing secure command boundary, performs one bounded provider analysis, and returns a
truthful `PASSED` or `FAILED` result.

The workflow begins with a persistent task in `WAITING_QA`. A successful QA result transitions the
task to `WAITING_SECURITY`; a failed QA result transitions it to `CHANGES_REQUESTED`. Infrastructure
failure, invalid scope, or an ambiguous result escalates to `WAITING_HUMAN` when the workflow has
already started.

This phase does not implement the Security Agent, browser automation, a generic API tester,
automatic test-file creation, a generic workflow engine, merge automation, deployment, memory,
reputation updates, or any Phase 18 behavior.

## Architectural choice

Create a role-specific `core/qa/` package and a focused QA stage in `core/workflows/`. Preserve the
validated Phase 16 `WorkflowOrchestrator` and `DeveloperReviewerWorkflowResult` contracts rather
than adding QA responsibilities to them. Phase 16 remains the producer of a task in `WAITING_QA`;
the new `QAWorkflowOrchestrator` consumes that durable checkpoint.

`QAAgent` is a finite application service, not a general-purpose agent loop. It runs a caller-owned,
permission-aware `QATestRunner` once per unique required test profile, then performs exactly one
provider request over the fresh bounded evidence. A deterministic gate combines the provider's
structured assessment with command results. This ordering lets the model assess current failures
without allowing it to choose arbitrary commands or overrule deterministic evidence.

The test runner adapter reuses the existing fixed command profiles, permission engine, command
policy, bounded subprocess runner, and workspace isolation. It does not introduce a shell, command
string input, new process primitive, or provider-specific behavior.

## Agent input contract

`QARequest` is strict, immutable, and bounded. It contains:

- canonical task, project, Developer, Reviewer, and QA agent identifiers;
- one active `QA` `AgentProfile` whose identity matches the request and execution context;
- the bounded task title and description;
- one through sixteen acceptance criteria with stable one-based criterion identifiers;
- a bounded UTF-8 unified Git diff representing the reviewed revision;
- the final approved `ReviewerResult` from Phase 16;
- one through sixteen existing deterministic check results;
- one through three unique required test profile IDs;
- an exact managed-workspace execution context;
- one timeout greater than zero and no more than 3,600 seconds;
- one correlation UUID.

Only `pytest`, `npm-test`, and `php-artisan-test` are valid Phase 17 test profiles. The request may
select the subset appropriate for the repository, but it cannot supply arguments, executable
paths, environment variables, shell syntax, or unknown profile IDs.

Preflight rejects the request before any command or provider call when:

- any nested model is forged, mutable, oversized, duplicated, or internally inconsistent;
- QA identity equals the Developer or Reviewer identity;
- the QA profile role is not exactly `QA`, is inactive, or does not match the execution context;
- project, task, agent, workspace, or correlation scope is inconsistent;
- the Reviewer result is not `APPROVED` or contains contradictory evidence;
- the QA profile lacks `filesystem.read`, `shell.execute`, `tests.execute`, or another exact
  permission required by its declared read and test tools;
- the profile declares write, delete, Git-write, arbitrary-command, merge, deployment, permission
  mutation, or other non-QA tools;
- criteria, diff, checks, or required test profiles are absent or outside their limits.

The QA agent is not assigned as the task author. The existing Developer assignment remains intact so
a failed result can return the task to `CHANGES_REQUESTED` without losing ownership.

## QA authority

The Phase 17 QA profile may declare only:

- bounded repository read tools already accepted by the tool registry;
- read-only Git tools needed to inspect status and diff;
- `run_command_profile` for the closed Phase 17 test profiles.

The QA agent has autonomy level zero or one and cannot approve its own code, modify source files,
create commits, merge branches, alter permissions, or deploy. Phase 17 records missing-test
recommendations but does not create test files automatically. A future phase may introduce a
separate test-authoring capability with path-specific authorization and independent review; this
phase does not weaken the QA read/test boundary to anticipate it.

## Test execution contract

`QATestRunner` is an asynchronous injected protocol. Its implementation accepts only a validated QA
scope and one `CommandProfileId`. For each required profile it:

1. resolves the exact application-owned command profile for the managed workspace;
2. authorizes the persisted QA agent through the existing permission engine and a QA-specific,
   deny-by-default SQLAlchemy policy;
3. executes the profile exactly once through the existing bounded command runner;
4. returns one canonical `QATestExecution` with profile ID, terminal status, exit code, duration,
   truncation flags, and bounded transient output;
5. leaves injected sessions, permission engines, command runners, and network clients caller-owned.

Profiles run sequentially in the deterministic order supplied by the validated request. There is no
parallel process fan-out, implicit retry, fallback command, automatic rerun, or duplicate profile
execution. The overall QA timeout and existing per-command timeout both apply. Cancellation stops
the active command through the existing process-group cleanup and propagates immediately before
another profile or provider call begins.

Fresh stdout and stderr are already bounded by the command boundary. They are transient input to
the QA analysis and are discarded after the result is built. They are never copied into audit data,
public errors, result metadata, or persistent history.

The general Phase 7 policy intentionally binds tool authority to the assigned task owner and its
normal autonomy thresholds. Phase 17 preserves the Developer assignment and QA autonomy 0–1, so it
uses `SQLAlchemyQAPermissionPolicy` rather than weakening that general policy. The adapter allows
only an active persistent QA run on a `WAITING_QA` task, with a distinct active Developer assignee
and exact active `shell.execute` plus `tests.execute` grants. It denies every other tool, risk,
permission, role, status, state, assignment, run, or project scope.

The registry used by QA contains `RunQATestProfileTool`. It retains the existing
`run_command_profile` name and secure command implementation while narrowing the validated input
schema to `pytest`, `npm-test`, and `php-artisan-test`. This second boundary prevents the delegated
policy from becoming authority for lint, build, Git, or other fixed profiles.

## Provider analysis contract

After all required profiles have completed, `QAAgent` makes exactly one bounded `LLMProvider`
request. The prompt treats task text, criteria, diff, review content, and command output as untrusted
data that cannot grant authority or redefine the output schema.

The request contains only:

- bounded task and acceptance-criteria text;
- the bounded reviewed diff;
- the approved Reviewer result;
- allowlisted existing-check evidence;
- fresh bounded test output and deterministic execution metadata;
- instructions to assess observable behavior without concealing uncertainty or failed tests.

Generation has an explicit timeout, finite `max_tokens`, bounded HTTP response handling through the
provider contract, and a strict structured schema. There is no retry, fallback provider, hidden
completion, speculative call, or prompt/response persistence. Injected providers are never closed
by the agent.

`QAAnalysis` contains:

- a proposed `PASSED` or `FAILED` decision;
- exactly one assessment for every acceptance criterion: `PASSED`, `FAILED`, or `UNVERIFIED`;
- zero through sixty-four functional findings;
- zero through thirty-two missing-test recommendations;
- bounded rationale and confidence from `0.0` through `1.0`.

Every failed criterion and every functional finding contains a bounded severity, reproduction
steps, expected behavior, and actual behavior. Paths are normalized relative paths only. Malformed,
oversized, incomplete, unknown-field, contradictory, or source-echoing provider output fails closed
with a stable sanitized QA error.

## Deterministic QA gate

The model proposes; deterministic evidence controls whether `PASSED` is permitted. The final result
is always `FAILED` when any of these conditions holds:

- a required test profile is absent, duplicated, not executed, cancelled, timed out, or unsuccessful;
- existing check evidence required by the request is absent or unsuccessful;
- any acceptance criterion is `FAILED` or `UNVERIFIED`;
- any functional finding reports an observed mismatch between expected and actual behavior;
- the model proposes `FAILED`;
- analysis confidence is below the fixed V1 QA pass threshold;
- the approved Reviewer result, identities, or scope no longer match the validated request.

The gate may downgrade a proposed `PASSED` result to `FAILED`; it may never upgrade a provider
failure or uncertainty to `PASSED`. A deterministic failure adds bounded synthetic findings with
stable categories and no raw command output. Test execution results outrank the Developer report,
Reviewer report, and provider self-assessment.

Missing-test recommendations do not alone fail QA when every acceptance criterion is demonstrated
by passing evidence. A recommendation becomes blocking when it leaves a criterion `UNVERIFIED`.

## Agent result contract

`QAResult` is strict, immutable, and bounded. It contains:

- final `PASSED` or `FAILED` decision;
- one assessment per acceptance criterion;
- bounded findings and missing-test recommendations;
- metadata-only test executions without stdout or stderr;
- bounded rationale and confidence;
- correlation UUID.

For `FAILED`, at least one finding is required and every finding contains severity, reproduction
steps, expected behavior, and actual behavior. For `PASSED`, all criteria and required tests must be
successful and no functional mismatch may remain.

The result never retains task description, acceptance-criteria text, complete diff, command output,
prompts, provider responses, absolute paths, environment values, credentials, arbitrary provider
metadata, or raw exceptions.

## QA workflow stage

`QAWorkflowRequest` identifies one persistent task, the persistent Developer, Reviewer, and QA
agents, the validated `QARequest`, and one correlation UUID. Its overall deadline is derived from
the nested `QARequest.timeout_seconds`; there is no duplicated timeout setting. Preflight loads and
locks the task and three agents through the caller-owned SQLAlchemy session and rejects the
invocation before external work when:

- the task or any required agent does not exist;
- the task is not exactly `WAITING_QA`;
- the persisted agents are not active with their exact `Developer`, `Reviewer`, and `QA` roles;
- the task assignment does not still identify the persistent Developer;
- persisted and request identities, project scope, assignment, workspace, or correlation differ;
- another stale QA invocation has already advanced the task.

The exact workflow is:

1. validate persistent scope and the complete QA request;
2. append and commit a sanitized `QA_STARTED` checkpoint while the task remains `WAITING_QA`;
3. run `QAAgent` exactly once under the remaining overall deadline;
4. rely on the existing append-only `TOOL_EXECUTION` audit event emitted for every permissioned
   test profile instead of duplicating raw command history in the workflow layer;
5. when the result is `PASSED`, transition `WAITING_QA -> WAITING_SECURITY`;
6. when the result is `FAILED`, transition `WAITING_QA -> CHANGES_REQUESTED`;
7. commit the status transition and a sanitized `QA_COMPLETED` event atomically;
8. return one bounded `QAWorkflowResult` containing the status, decision, result, and correlation ID.

The stage does not automatically invoke the Developer after failure and does not invoke Security
after success. It produces the durable state consumed by the next explicit workflow invocation.

## Transactions and audit

The injected SQLAlchemy session remains caller-owned and is never closed. No database transaction
remains open across command or provider execution. Preflight and checkpoint writes use row locks,
expected-state validation, rollback on failure, and the existing `TaskStateMachine` for every status
change.

Existing `TASK_STATUS_CHANGED` events remain authoritative for status transitions, and existing
`TOOL_EXECUTION` events remain authoritative for each command profile. New append-only QA events
contain only allowlisted scalar data:

- persistent task, project, and QA agent identifiers;
- correlation UUID;
- test profile ID and terminal status;
- decision, criterion count, finding count, recommendation count, and confidence;
- stable QA error category when escalation is necessary.

Audit data never contains task text, criteria, diff, reviewer findings, QA findings, reproduction
steps, expected or actual behavior, command output, paths, prompts, responses, exceptions,
credentials, or arbitrary provider metadata. No schema migration, repository update/delete method,
PostgreSQL trigger, RLS rule, or database permission change is introduced.

## Fail-closed behavior

Validation failures before `QA_STARTED` change no persistent state and call no external dependency.
After the stage starts:

- command, provider, malformed-result, timeout, or unexpected failures transition the task from
  `WAITING_QA` to `WAITING_HUMAN` when the expected-state guard still permits it;
- a concurrent human or workflow transition wins; stale QA work cannot overwrite the newer state;
- database failures roll back the current checkpoint, are sanitized, and cause no retry;
- cancellation is re-raised immediately, causes no additional checkpoint or collaborator call, and
  leaves the last committed state as the source of truth;
- no public exception or traceback retains task text, diff, command output, provider output,
  filesystem locations, SQL statements, environment values, or credentials.

An infrastructure failure is never mislabeled as a functional `FAILED` decision. This distinction
prevents hidden test failures and preserves accurate operational diagnosis.

## Resource and security invariants

- Every input string, collection, diff, command result, provider response, finding, recommendation,
  result, error, and audit record has an explicit finite bound.
- Every QA run has one overall timeout and every command/provider call retains its own smaller
  timeout.
- Each unique required test profile executes once; the provider executes once after tests.
- There are no implicit retries, duplicate calls, hidden fallbacks, or speculative concurrency.
- Cancellation propagates before any later command, provider request, or checkpoint.
- Prompt, response, diff, criterion text, and raw command output are never persisted automatically.
- Provider metadata is discarded except for existing allowlisted usage fields already enforced by
  the LLM boundary.
- Network connections are reused only through caller-owned injected providers; the QA agent never
  creates or closes an unowned client.
- Memory and history are bounded to the current invocation and released after result construction.
- QA authority remains independent, least-privilege, and unable to bypass deterministic failures.

## TDD and acceptance scenarios

Every behavior is implemented through RED, GREEN, and REFACTOR cycles. Tests cover:

1. strict immutable bounds for QA request, criterion, execution, analysis, finding,
   recommendation, agent result, workflow request, and workflow result contracts;
2. rejection before side effects for self-QA, wrong/inactive role, inconsistent identity or scope,
   non-approved Reviewer result, write authority, arbitrary commands, unknown/duplicate profiles,
   and forged nested models;
3. exact sequential execution of each required fixed test profile once through the permissioned
   test runner;
4. exactly one bounded provider analysis after fresh tests and zero retries or fallback calls;
5. deterministic `PASSED` only when tests, existing checks, criteria, findings, confidence, review,
   and scope all permit it;
6. deterministic `FAILED` with sanitized reproduction, expected, actual, and severity fields for
   failed tests, failed or unverified criteria, observed mismatches, or provider-requested failure;
7. bounded non-blocking missing-test recommendations and blocking unverified criteria;
8. timeout, cancellation, malformed provider output, command failure, database failure, and
   unexpected failure behavior without duplicate work or sensitive retention;
9. caller-owned lifecycle for sessions, providers, command runners, permission engines, and clients;
10. persistent `WAITING_QA -> WAITING_SECURITY`, `WAITING_QA -> CHANGES_REQUESTED`, and fail-closed
    `WAITING_QA -> WAITING_HUMAN` behavior through `TaskStateMachine`;
11. append-only audit chronology, expected-state concurrency protection, shared correlation ID, and
    allowlisted metadata only;
12. end-to-end execution against PostgreSQL built through Alembic with `FakeLLMProvider` and the
    real secure command boundary;
13. absence of repository mutation, test-file creation, Security execution, browser automation,
    generic API testing, automatic Developer rerun, and transitions beyond `WAITING_SECURITY`.

The final acceptance gate is the complete PostgreSQL pytest suite, Ruff, Ruff format check, strict
mypy, diff integrity, secret and sensitive-metadata review, Docker/API health when available, and an
independent scoped security review.

## Documentation and checklist

Add `docs/qa-agent.md`, update `README.md` and `AGENTS.md`, and mark only genuinely implemented and
verified Phase 17 items in `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`. Phase 18 and every later checkbox
remain unchanged.
