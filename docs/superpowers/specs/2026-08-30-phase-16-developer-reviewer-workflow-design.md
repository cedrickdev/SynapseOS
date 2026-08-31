# Phase 16 Developer–Reviewer Workflow Design

## Scope

Phase 16 introduces the first real SynapseOS multi-agent workflow. A minimal
`WorkflowOrchestrator` assigns one persistent `READY` task to one Developer, runs the bounded
`DeveloperAgent`, hands only validated evidence to an independent `ReviewerAgent`, and repeats the
correction cycle until the review is approved or the configured cycle limit is reached.

The successful terminal state for this phase is `WAITING_QA`. Phase 16 does not implement a QA
agent, Security agent, merge, pull-request automation, event bus, background worker, scheduler,
reputation update, memory write, deployment, or generic workflow language.

## Architectural choice

Create a focused `core/workflows/` application package. The orchestrator composes existing
Developer, Reviewer, `TaskStateMachine`, and append-only audit behavior; it does not duplicate
their internal rules. Agent calls are represented by narrow protocols so deterministic fakes can
test orchestration without weakening the concrete agents' contracts.

The workflow receives one strict immutable `DeveloperReviewerWorkflowRequest` plus a handoff
builder. The handoff builder is responsible for obtaining the current bounded Git diff after each
Developer run and constructing a complete `ReviewerRequest`. This keeps repository reads outside
the orchestrator and guarantees that a correction cycle reviews fresh evidence rather than a stale
first-cycle diff.

The orchestrator is intentionally not a reusable graph engine. The Phase 16 flow is explicit code
with closed states and decisions. A generic event-driven workflow engine is deferred until multiple
real workflows demonstrate a stable abstraction.

## Persistent identities and assignment

The workflow request identifies:

- one persistent PostgreSQL task UUID;
- one persistent Developer agent UUID;
- one persistent Reviewer agent UUID;
- the bounded `DeveloperRequest` used for each Developer cycle;
- `max_review_cycles`, from 1 through 10;
- one workflow timeout, greater than zero and no more than 3,600 seconds;
- one correlation UUID shared by workflow audit events.

Preflight loads the task and both agents in the injected SQLAlchemy session and fails before any
agent call when:

- the task does not exist or is not `READY`;
- either agent does not exist;
- Developer and Reviewer persistent UUIDs are equal;
- the Developer role or Reviewer role is incorrect;
- either agent is `OFFLINE` or `BLOCKED`;
- `DeveloperRequest.profile.id` does not match the persistent Developer slug;
- the runtime task ID, execution-context task ID, project ID, agent ID, or correlation ID does not
  match persistent workflow scope;
- Developer and Reviewer profile identities are not independent;
- task criteria or descriptions cannot be represented by the bounded agent contracts.

Assignment sets `task.assigned_agent_id` to the Developer's persistent UUID and then applies
`READY -> ASSIGNED` through `TaskStateMachine`. The Reviewer is never assigned as the author.

## Workflow state machine

The exact Phase 16 sequence is:

1. validate the complete request and persistent scope;
2. assign the Developer and transition `READY -> ASSIGNED`;
3. transition `ASSIGNED -> IN_PROGRESS`;
4. run the Developer exactly once for the current review cycle;
5. transition `IN_PROGRESS -> WAITING_REVIEW`;
6. build a fresh bounded handoff from the Developer result and current diff;
7. run the Reviewer exactly once for the current review cycle;
8. if approved, transition `WAITING_REVIEW -> WAITING_QA` and return;
9. if changes are requested, transition `WAITING_REVIEW -> CHANGES_REQUESTED`;
10. when another cycle is available, transition `CHANGES_REQUESTED -> IN_PROGRESS` and repeat;
11. when the limit is exhausted, transition `CHANGES_REQUESTED -> WAITING_HUMAN` and return a
    fail-closed exhausted result.

Only `TaskStateMachine` may modify task status. The orchestrator never assigns `WAITING_SECURITY`,
`COMPLETED`, or any later-phase state.

## Transaction and checkpoint policy

The injected SQLAlchemy session remains caller-owned and is never closed. The orchestrator commits
each state transition and its associated append-only audit event before invoking the next external
agent operation. This avoids holding a database transaction open during LLM or tool execution and
leaves a durable, truthful checkpoint if the process stops.

Assignment and `READY -> ASSIGNED` are committed atomically. Every later status transition and its
workflow event are committed atomically. A database failure is rolled back and converted to a safe
workflow error; it never causes an agent retry. Already committed checkpoints remain historical
truth and are not rewritten.

The orchestrator does not own the surrounding session lifecycle and never closes, disposes, or
reconfigures it.

## Handoff contract

`ReviewerHandoffBuilder` is an asynchronous injected protocol with one method that receives the
validated workflow scope, the latest `DeveloperResult`, and the one-based review cycle. It returns
one strict `ReviewerRequest`.

The orchestrator revalidates the returned request and requires:

- persistent task and project identifiers encoded in their canonical lowercase UUID text;
- Developer and Reviewer IDs equal to their validated profile slugs;
- the exact latest Developer report;
- checks equal to a lossless, allowlisted conversion of the latest Developer checks;
- required check profiles equal to the Developer request;
- title, description, criteria, and diff within Reviewer bounds;
- no self-review and no write-capable Reviewer profile.

The handoff includes no Developer conversation, runtime history, tool output, prompts, model
responses, absolute paths, environment values, secrets, or earlier-cycle diff. The builder is
called once per completed Developer cycle and is never retried implicitly.

## Workflow result

`DeveloperReviewerWorkflowResult` is immutable and bounded. It contains:

- terminal task status (`WAITING_QA` or `WAITING_HUMAN` only);
- terminal workflow outcome (`APPROVED` or `REVIEW_CYCLES_EXHAUSTED`);
- number of completed Developer cycles;
- number of completed Reviewer cycles;
- the final sanitized `ReviewerResult`;
- the final bounded Developer report;
- correlation UUID.

It does not retain complete `DeveloperResult` instances, runtime histories, diffs, prompts, raw
provider responses, command output, or all previous review results.

## Audit contract

Existing `TASK_STATUS_CHANGED` events remain authoritative for every state transition. Phase 16
adds bounded append-only events for workflow facts that are not represented by status alone:

- `WORKFLOW_STARTED` after validated assignment;
- `DEVELOPER_HANDOFF_CREATED` after a safe Reviewer request is built;
- `REVIEW_COMPLETED` after each Reviewer decision;
- `REVIEW_CYCLE_EXHAUSTED` when the configured limit is reached;
- `WORKFLOW_COMPLETED` when the task reaches `WAITING_QA`.

Events use the request correlation UUID. Data is allowlisted to stable identifiers, one-based cycle
number, decision, score, finding count, and configured cycle limit. Audit data never contains task
text, acceptance criteria, diff, findings, rationale, prompts, responses, command output, paths,
exceptions, credentials, or arbitrary provider metadata.

Audit insertion uses the existing append-only model. Normal application code exposes no update or
delete operation. No PostgreSQL trigger, RLS policy, or new permission scheme is introduced.

## Fail-closed behavior

Validation failures occur before assignment and before agent calls. After workflow start:

- an invalid or unsafe handoff moves the task from `WAITING_REVIEW` to `WAITING_HUMAN` and raises a
  stable sanitized workflow error;
- a Developer or Reviewer application error moves the current task to `WAITING_HUMAN` when that
  transition is legal, records only its stable error category, and raises a sanitized workflow
  error;
- an overall workflow timeout follows the same safe escalation path and performs no retry;
- cancellation is never converted into a normal failure and is re-raised immediately; the last
  committed task checkpoint identifies where execution stopped;
- database failures are rolled back, sanitized, and never retried implicitly;
- a Reviewer decision can never be upgraded by the orchestrator.

No exception message includes user content, diff content, provider content, command output,
filesystem locations, database statements, credentials, or raw traceback data.

## Resource bounds and ownership

- `max_review_cycles` is explicit and bounded from 1 through 10.
- One overall timeout bounds the full workflow; existing per-agent limits remain in force.
- Each cycle invokes Developer once, handoff builder once, and Reviewer once.
- There is no implicit retry, provider fallback, duplicated call, or speculative parallel call.
- Cancellation propagates without another model or tool call.
- The result retains only the final bounded reports and scalar counters.
- The orchestrator stores no prompt, response, diff, command output, or conversation history.
- Injected agents, providers, tools, handoff builders, sessions, and network clients remain
  caller-owned and are never closed.

## TDD and acceptance scenarios

Tests must observe RED before production implementation and cover:

1. strict immutable and bounded workflow request/result contracts;
2. rejection before side effects for missing task/agent, non-`READY` state, wrong role, offline or
   blocked agent, self-review, mismatched task/project/agent/correlation scope, and type-confused
   model copies;
3. atomic assignment and audited `READY -> ASSIGNED -> IN_PROGRESS` transitions;
4. one-cycle approval ending in `WAITING_QA` with one Developer and one Reviewer call;
5. one requested correction followed by approval, with fresh handoff evidence and exactly two calls
   to each agent;
6. repeated requested changes exhausting the configured limit and ending in `WAITING_HUMAN`;
7. handoff revalidation rejects stale reports, checks, identities, scope, write-capable Reviewer, and
   oversized or malformed evidence;
8. append-only transition and workflow audit chronology, shared correlation ID, and allowlisted
   non-sensitive data;
9. Developer, Reviewer, handoff, timeout, database, and cancellation failure behavior without
   hidden retries or duplicate calls;
10. result/history bounds and caller-owned resource lifecycle;
11. end-to-end execution against real PostgreSQL created through Alembic and deterministic
    `FakeLLMProvider` instances;
12. no QA/Security execution and no transition beyond `WAITING_QA`.

The complete gate remains the full pytest suite, Ruff, Ruff format check, strict mypy, diff
integrity, Docker build, PostgreSQL health, Alembic head, API health, and an independent final
review.

## Documentation and checklist

Add `docs/developer-reviewer-workflow.md`, update `README.md` and `AGENTS.md`, and mark only genuinely
verified Phase 16 checklist items in `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`. Phase 17 and all later
checkboxes remain unchanged.
