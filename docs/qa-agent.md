# QA Agent

Phase 17 adds one independent, bounded `QAAgent` and one persistent QA workflow stage. It consumes
an approved Reviewer result, executes fresh fixed test profiles, evaluates the acceptance criteria,
and returns `PASSED` or `FAILED`. It does not modify source files, author tests, invoke Security, or
advance beyond `WAITING_SECURITY`.

## Input and identity boundary

`QARequest` is strict, immutable, and bounded. It contains the persistent task and project scope,
distinct Developer, Reviewer, and QA slugs, an active `QA` profile, task text, one through sixteen
acceptance criteria, a bounded diff, the approved Reviewer result, existing check metadata, one
through three required test profiles, the exact tool execution context, one timeout, and one
correlation UUID.

Preflight reconstructs the complete request before any tool or provider call. It rejects:

- self-QA or any shared Developer, Reviewer, and QA identity;
- a non-approved Reviewer result;
- an inactive or non-`QA` profile;
- mismatched task, project, run, profile, tool, or correlation scope;
- missing `filesystem.read`, `shell.execute`, or `tests.execute` authority;
- write, delete, Git-write, deployment, database-write, network, or permission-mutation authority;
- undeclared or non-QA tools; and
- duplicate, missing, non-test, or unbounded command profiles.

The profile may expose bounded repository reads, read-only Git evidence, and the fixed command
adapter. Phase 17 records missing-test recommendations only. Test authoring remains deferred and
therefore cannot acquire write authority through a recommendation.

## Delegated permission boundary

The Developer remains the task assignee so authorship and responsibility are preserved. The QA
agent instead receives a narrowly delegated execution boundary through
`SQLAlchemyQAPermissionPolicy`. It authorizes exactly one capability when every condition holds:

- the tool is `run_command_profile`, its risk is `HIGH`, and its required grants are exactly
  `shell.execute` plus `tests.execute`;
- the task is exactly `WAITING_QA` and remains assigned to a distinct active `Developer`;
- an active persistent `AgentRun` ties the requesting agent to the same task and project;
- that agent has the exact active role `QA`, status `ASSIGNED` or `WORKING`, and autonomy 0 or 1;
- both explicit grants are active, unrevoked, unexpired, and global or scoped to the same project.

Every mismatch is denied. This policy does not authorize reads, writes, arbitrary shell commands,
builds, lint profiles, Git commands, or later workflow stages. `RunQATestProfileTool` keeps the
existing tool name and secure command implementation but narrows its input schema to only:

- `pytest`
- `npm-test`
- `php-artisan-test`

The command policy still supplies the exact executable, arguments, managed working directory,
sanitized environment, timeout, output ceilings, process-group cancellation, and cleanup. The
model cannot provide executable paths, flags, environment variables, or free-form command text.

## Exact execution and one-shot analysis

`PermissionedQATestRunner` executes each unique requested test profile sequentially and exactly
once. A completed test process is evidence even when its exit code is non-zero. Tool denial,
timeout, malformed output, audit failure, or command infrastructure failure becomes one sanitized
operational QA error; it is never converted into a functional test failure.

Transient stdout and stderr are each capped at 32 KiB before analysis. `QAAgent` then performs
exactly one provider-neutral `LLMProvider.generate()` call with temperature 0, a caller-selected
generation ceiling no greater than 4,096 tokens, a provider timeout no greater than 30 seconds,
empty provider metadata, and a 128 KiB response ceiling. There is no retry, fallback provider,
repair call, speculative request, or implicit duplicate.

The provider returns complete criterion assessments, bounded findings, optional missing-test
recommendations, a rationale, and confidence. Repository content and test output are explicitly
untrusted data and cannot alter QA authority.

## Deterministic QA gate

Application evidence has priority over the provider proposal. `PASSED` requires all of the
following:

- every required profile ran exactly once and succeeded;
- every acceptance criterion is covered and marked `PASSED`;
- no `HIGH` or `CRITICAL` finding exists;
- the provider proposed `PASSED`; and
- confidence is at least `0.70`.

Any failed condition produces `FAILED` with an actionable finding. The gate may downgrade a model
pass but never upgrade a model failure or conceal deterministic failed tests. Public `QAResult`
retains only profile ID, status, exit code, duration, and truncation metadata for test executions;
stdout and stderr are discarded.

## Persistent workflow stage

`QAWorkflowOrchestrator` accepts only a persistent task in `WAITING_QA`, with active and distinct
Developer, Reviewer, and QA records and the Developer assignment preserved. Its exact flow is:

```text
validate and row-lock persistent scope
  -> commit QA_STARTED while remaining in WAITING_QA
  -> run QAAgent exactly once
  -> PASSED: WAITING_QA -> WAITING_SECURITY; commit QA_COMPLETED
  -> FAILED: WAITING_QA -> CHANGES_REQUESTED; commit QA_COMPLETED
  -> operational failure: WAITING_QA -> WAITING_HUMAN; commit QA_ESCALATED
```

The orchestrator never invokes Developer again, starts Security, merges code, or completes the
task. A later coordinator may explicitly hand `CHANGES_REQUESTED` back to Developer or start Phase
18 from `WAITING_SECURITY`.

The task row is reacquired with `SELECT FOR UPDATE` before every checkpoint. Correlated lifecycle
facts are matched explicitly rather than inferred from timestamp or random-UUID ordering. A stale,
duplicate, completed, or concurrently superseded invocation cannot overwrite newer task state.

## Audit, failures, and lifecycle

The append-only audit records `QA_STARTED`, the existing `PERMISSION_EVALUATED` and
`TOOL_EXECUTION` facts, `TASK_STATUS_CHANGED`, and either `QA_COMPLETED` or `QA_ESCALATED`. QA
events contain only stable identifiers, decisions, counts, confidence, profile statuses, and safe
error categories. They never contain task text, acceptance criteria, diffs, findings, paths,
reproduction steps, prompts, responses, stdout, stderr, environment values, credentials, provider
diagnostics, or raw exceptions.

The nested QA timeout is the sole workflow deadline. Command and provider limits remain smaller
independent ceilings. Cancellation propagates immediately without escalation or another call; a
committed `QA_STARTED` remains available for explicit recovery. Operational failures after start
receive only a bounded best-effort escalation transaction and never retry QA. Injected sessions,
providers, command runners, tools, and network clients remain caller-owned and are never closed by
the agent or orchestrator. No request, result, output, prompt, response, or history is retained on
the agent instance.

## Testing

The focused suite uses PostgreSQL built through Alembic and a deterministic fake provider while
executing a real bounded test process:

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/qa \
  tests/workflows/test_qa_integration.py \
  tests/database/test_qa_permission_policy.py \
  tests/tools/test_qa_command_tool.py -q
```

Coverage includes exact-once execution, functional pass and failure, missing grants, strict role
and state delegation, non-test profile rejection, one provider call, deterministic downgrade,
timeout, cancellation, output limits, confidentiality, append-only audit, persistent transitions,
and caller-owned resource lifecycle.

## Deferred work

Phase 18 Security execution, test authoring, correction-loop coordination, generic multi-agent
orchestration, provider routing, MCP, background workers, merge automation, deployment, memory,
reputation aggregation, and frontend behavior remain unimplemented.
