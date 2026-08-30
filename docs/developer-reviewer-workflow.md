# Developer–Reviewer Workflow

Phase 16 provides the first concrete SynapseOS multi-agent workflow. It composes one persistent
`READY` task, one Developer agent, one independent read-only Reviewer agent, and a bounded fresh
evidence handoff. The public entry point is `core.workflows.WorkflowOrchestrator`.

## Boundary and configuration

`DeveloperReviewerWorkflowRequest` identifies the persistent task UUID, Developer UUID, Reviewer
UUID, the bounded `DeveloperRequest`, the validated Reviewer profile, a correlation UUID, and two
explicit limits:

- `max_review_cycles` is an integer from 1 through 10.
- `timeout_seconds` is greater than zero and no more than 3,600 seconds for the whole workflow.

Preflight loads the task and both persistent agents from the caller-owned SQLAlchemy session. It
rejects missing or non-`READY` tasks, missing or inactive agents, incorrect roles, self-review,
profile or runtime scope mismatches, and inconsistent bounded task criteria before assignment or
an agent call. The Developer and Reviewer identities must differ both by persistent UUID and by
profile slug.

The session is supplied by the caller. The orchestrator commits each durable checkpoint before the
next external call and never closes, disposes, or reconfigures the session. Injected agents,
providers, tools, handoff builders, and clients are also caller-owned.

## Exact flow

The workflow is explicit code with closed states and decisions:

```text
validate request and persistent scope
  -> assign Developer; READY -> ASSIGNED
  -> ASSIGNED -> IN_PROGRESS
  -> run Developer once
  -> IN_PROGRESS -> WAITING_REVIEW
  -> build and validate a fresh Reviewer handoff once
  -> run Reviewer once
  -> APPROVED: WAITING_REVIEW -> WAITING_QA; return
  -> CHANGES_REQUESTED: WAITING_REVIEW -> CHANGES_REQUESTED
  -> if a cycle remains: CHANGES_REQUESTED -> IN_PROGRESS; repeat
  -> if the limit is exhausted: CHANGES_REQUESTED -> WAITING_HUMAN; return
```

Only `TaskStateMachine` changes task status. The orchestrator does not assign `WAITING_SECURITY`,
`COMPLETED`, or any later-phase state. `WAITING_QA` is the only successful terminal state in this
phase.

## Handoff contents and freshness

`ReviewerHandoffBuilder` is an asynchronous caller-supplied boundary. It receives the validated
workflow context, the latest bounded `DeveloperResult`, and the one-based cycle number. It must
return one strict `ReviewerRequest` containing:

- canonical task and project UUID text;
- independent Developer and Reviewer profile slugs;
- the validated title, description, and acceptance criteria;
- the current bounded diff;
- the exact latest Developer report;
- a lossless allowlisted conversion of the latest Developer check metadata; and
- the Developer request's required check profiles.

The orchestrator revalidates the complete request before running the Reviewer. The builder runs
once per completed Developer cycle and is never retried. A correction cycle therefore obtains a
new diff and a new latest Developer result rather than reusing first-cycle evidence.

## Checkpoints and audit

Every task transition is persisted together with its authoritative `TASK_STATUS_CHANGED` event.
Phase 16 adds these bounded correlated workflow events:

| Event | Recorded fact |
| --- | --- |
| `WORKFLOW_STARTED` | Developer/Reviewer slugs and cycle limit after assignment |
| `DEVELOPER_HANDOFF_CREATED` | one-based cycle after handoff validation |
| `REVIEW_COMPLETED` | cycle, decision, score, and finding count |
| `REVIEW_CYCLE_EXHAUSTED` | final cycle and configured limit |
| `WORKFLOW_COMPLETED` | final approved cycle |

Audit data is an allowlist of stable identifiers, cycle numbers, decisions, scores, counts, and
limits. It does not persist prompts, provider responses, conversation history, diffs, findings,
rationales, command output, paths, environment values, exceptions, credentials, or arbitrary
provider metadata. Events share the request correlation UUID and use the existing append-only
audit model.

## Result and resource bounds

`DeveloperReviewerWorkflowResult` is immutable and final-only. It contains the terminal task state,
terminal workflow outcome, equal Developer/Reviewer cycle counts, the final bounded Developer
report, the final sanitized Reviewer result, the cycle limit, and the correlation UUID. It does
not retain earlier results, diffs, prompts, responses, runtime histories, or command output.

Each cycle invokes Developer once, the handoff builder once, and Reviewer once. There is no hidden
retry, provider fallback, duplicate call, speculative parallel call, or unbounded collection. The
overall timeout follows the same safe escalation path as a collaborator failure. Cancellation is
re-raised immediately without another call; the last committed checkpoint remains the durable
location of interruption. Database failures are rolled back and sanitized without retry.

## Safe failures

Validation failures occur before side effects. After assignment, an unsafe handoff, collaborator
failure, timeout, or persistence failure safely escalates the task to `WAITING_HUMAN` when that
transition is legal, records only a stable error category, and raises a sanitized `WorkflowError`.
Cancellation is not converted into a normal failure. Raw exception messages and tracebacks never
reach the public error or audit data. A Reviewer decision is never upgraded by the orchestrator.

## Usage example

```python
request = DeveloperReviewerWorkflowRequest(
    task_id=task.id,
    developer_agent_id=developer.id,
    reviewer_agent_id=reviewer.id,
    developer_request=developer_request,
    reviewer_profile=reviewer_profile,
    max_review_cycles=3,
    timeout_seconds=120.0,
    correlation_id=developer_request.execution_context.correlation_id,
)

result = await WorkflowOrchestrator(
    session,
    developer=developer_agent,
    reviewer=reviewer_agent,
    handoff_builder=handoff_builder,
).run(request)

assert result.task_status in {TaskStatus.WAITING_QA, TaskStatus.WAITING_HUMAN}
```

The caller remains responsible for the surrounding session and dependency lifecycle. A concrete
deployment must supply the existing bounded `DeveloperAgent`, read-only `ReviewerAgent`, and a
handoff builder that obtains current repository evidence through approved repository boundaries.

## Phase 17 exclusions

Phase 16 does not implement or invoke a QA agent, Security agent, merge or pull-request automation,
event bus, background worker, scheduler, reputation update, memory write, deployment, or generic
workflow language. `WAITING_QA` is a handoff boundary only. Phase 17 owns QA validation and any
future transition out of that state; no Phase 17 behavior is present in this workflow.
