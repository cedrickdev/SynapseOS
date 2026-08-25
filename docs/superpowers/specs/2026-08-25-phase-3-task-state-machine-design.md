# Phase 3 Task State Machine Design

## Scope

Phase 3 centralizes every persisted `Task.status` change in a framework-independent state machine.
It defines explicit transitions, rejects invalid or untracked changes, and appends one audit event
in the same SQLAlchemy transaction as every accepted transition.

Phase 3 excludes HTTP CRUD endpoints, agents, LLM providers, executable tools, QA/security
engines, event-bus delivery, and all Phase 4 behavior.

## States and Migration

`TaskStatus` becomes:

```text
BACKLOG
READY
ASSIGNED
IN_PROGRESS
WAITING_REVIEW
CHANGES_REQUESTED
WAITING_QA
WAITING_SECURITY
BLOCKED
WAITING_HUMAN
COMPLETED
FAILED
CANCELLED
```

`WAITING_HUMAN` is retained because human approval and escalation are constitutional invariants.
It is intentionally additional to the twelve workflow states listed in the Phase 3 prompt.

The migration preserves existing rows:

- `DRAFT` becomes `BACKLOG`;
- `REJECTED` becomes `CHANGES_REQUESTED`;
- `DONE` becomes `COMPLETED`;
- all unchanged names retain their values.

The downgrade maps `WAITING_QA` and `WAITING_SECURITY` to `WAITING_REVIEW`, `FAILED` to `BLOCKED`,
and reverses the three renamed values. This downgrade is lossy by necessity and is documented in
the migration.

## Transition Graph

The normal delivery path is:

```text
BACKLOG -> READY -> ASSIGNED -> IN_PROGRESS -> WAITING_REVIEW
WAITING_REVIEW -> WAITING_QA -> WAITING_SECURITY -> COMPLETED
```

Correction and recovery paths are:

```text
WAITING_REVIEW -> CHANGES_REQUESTED -> IN_PROGRESS
WAITING_QA -> CHANGES_REQUESTED
WAITING_SECURITY -> CHANGES_REQUESTED
IN_PROGRESS -> BLOCKED -> READY
CHANGES_REQUESTED -> BLOCKED
IN_PROGRESS -> FAILED -> READY
WAITING_QA -> FAILED
WAITING_SECURITY -> FAILED
```

Every non-terminal state except `WAITING_HUMAN` may transition to `WAITING_HUMAN` or `CANCELLED`.
`WAITING_HUMAN` may transition only to `READY` or `CANCELLED`, forcing re-evaluation before work
resumes. `COMPLETED` and `CANCELLED` are terminal. Self-transitions are invalid.

## Application Interface

`core/tasks/state_machine.py` provides:

```python
class InvalidTaskTransitionError(ValueError): ...


class TaskTransitionValidationError(ValueError): ...


class TaskStateMachine:
    def __init__(self, session: Session) -> None: ...

    def can_transition(self, current: TaskStatus, target: TaskStatus) -> bool: ...

    def transition(
        self,
        task: Task,
        target: TaskStatus,
        *,
        actor_type: AuditActorType,
        actor_id: str | None,
        reason: str,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent: ...
```

`reason` must contain non-whitespace text. `actor_id` is mandatory except for `SYSTEM`. Metadata is
copied into the audit payload so caller mutations cannot rewrite the pending event. The method
mutates the task and adds the audit event but never commits; transaction ownership remains with the
caller.

## Audit Contract

Every accepted transition inserts one append-only `AuditEvent`:

```text
event_type = TASK_STATUS_CHANGED
action = transition_task_status
result = SUCCEEDED
project_id = task.project_id
task_id = task.id
actor_type = supplied actor type
actor_id = supplied actor identifier
data = {
  "from_status": <old value>,
  "to_status": <new value>,
  "reason": <required reason>,
  "metadata": <copied object>
}
```

Rejected transitions create no audit event because no state change occurred. The domain exception
contains the task identifier and both states without exposing metadata.

## Direct-Mutation Guard

A global SQLAlchemy `Session.before_flush` listener inspects persisted dirty `Task` instances. If
the status history changed without authorization recorded by `TaskStateMachine`, it raises
`UnauthorizedTaskStatusChangeError`. New tasks are allowed to receive their initial status.

The state machine records a one-flush authorization containing the exact task, source state, and
target state. The guard consumes only an exact match and clears authorizations after flush or
rollback. Other task fields remain normally editable.

This is an application-level guarantee. Direct SQL and privileged database clients can bypass it;
database triggers and dedicated PostgreSQL permissions remain outside Phase 3.

## Testing

- Pure contract tests cover every pair in the 13-by-13 state matrix.
- Validation tests cover empty reasons, missing non-system actor IDs, self-transitions, and terminal
  states.
- Real PostgreSQL tests prove task and audit persistence are atomic.
- Real PostgreSQL tests prove direct status assignment fails while non-status edits remain valid.
- Mutable metadata is copied and does not mutate the append-only audit payload.
- Alembic tests cover upgrade, downgrade, second upgrade, value conversion, and schema head.
- The complete pytest, Ruff, formatting, mypy, Docker migration, and health checks must pass.
