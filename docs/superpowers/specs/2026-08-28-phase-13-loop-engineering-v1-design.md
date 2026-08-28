# Phase 13 Loop Engineering V1 Design

**Date:** 2026-08-28
**Status:** Approved
**Scope:** One bounded autonomous agent runtime only

## Goal

Build the first controlled autonomous loop in SynapseOS. One agent observes a task, plans,
chooses one structured action, executes an already-registered tool through the existing secured
tool boundary, verifies the result, and either continues, completes, or escalates.

Phase 13 does not implement Phase 12 stack detection, multi-agent coordination, a Developer role,
free-form shell execution, a reputation engine, memory retrieval, or a scheduler.

## Architectural boundaries

`AgentRuntime` belongs in `core/runtime/`. It coordinates existing provider-neutral contracts and
must not depend on SQLAlchemy, FastAPI, Ollama, operating-system processes, or concrete tools.

The runtime consumes:

- an `LLMProvider` through a structured `LoopReasoner`;
- the existing `ToolExecutor` as the only tool execution path;
- a persistence-neutral `RuntimeAuditRecorder`;
- an immutable `ToolExecutionContext` that fixes agent, run, project, task, correlation, declared
  tools, and workspace scope.

The runtime never bypasses the registry, permission engine, human-approval decision, tool timeout,
or tool audit lifecycle already enforced by `ToolExecutor`.

## Loop state machine

One run follows this non-recursive state machine:

```text
START
  -> OBSERVE
  -> PLAN
  -> DECIDE
       -> COMPLETE -> REPORT -> COMPLETED
       -> ESCALATE -> REPORT -> ESCALATED
       -> TOOL_CALL -> ACT -> OBSERVE_RESULT -> VERIFY
            -> complete -> REPORT -> COMPLETED
            -> continue -> next bounded iteration
            -> escalate -> REPORT -> ESCALATED
```

The runtime checks the global deadline and every budget before beginning another external call.
There is no implicit retry. A second tool call happens only after a new valid LLM decision in a
new iteration.

## Structured LLM protocol

The concrete `LLMLoopReasoner` sends bounded provider-neutral `LLMRequest` values and decodes each
response with the existing strict structured-output decoder. It exposes five operations:

- `observe(task, bounded_history) -> RuntimeObservation`
- `plan(task, observation, bounded_history) -> RuntimePlan`
- `decide(task, observation, plan, bounded_history) -> RuntimeDecision`
- `verify(task, decision, tool_result, bounded_history) -> RuntimeVerification`
- `report(task, terminal_state, bounded_history) -> RuntimeReport`

Every response is one exact JSON object. Unknown fields, invalid enums, blank text, non-finite
numbers, oversized collections, malformed JSON, and unbounded tool arguments fail closed.

`RuntimeDecision.action` is one of `TOOL_CALL`, `COMPLETE`, or `ESCALATE`. A tool call contains
only a registered tool name and a bounded JSON object. The LLM cannot provide an executable,
working directory, environment, timeout override, permission override, or retry instruction.

The reasoner performs at most one provider call per operation and never retries, falls back, or
owns the injected provider lifecycle.

## Immutable contracts

`RuntimeLimits` contains:

- `max_iterations`: 1 through 100;
- `timeout_seconds`: finite, greater than zero, at most 3,600;
- `max_tool_calls`: 0 through 1,000;
- `max_failures`: 0 through 100;
- `max_tokens`: 1 through 10,000,000 cumulative reported tokens;
- `max_history_entries`: 1 through 1,000;
- `stagnation_window`: 2 through 20;
- `max_step_tokens`: 1 through 131,072 per LLM request.

`RuntimeTask` contains a bounded task identifier, objective, acceptance criteria, and no secrets.
The immutable terminal `RuntimeResult` contains only status, safe summary, counters, token usage,
elapsed duration, iteration count, terminal reason, and bounded safe step metadata.

Terminal statuses are `COMPLETED`, `ESCALATED`, `LIMIT_REACHED`, `TIMED_OUT`, and `FAILED`.

## Budget semantics

- An iteration starts at `OBSERVE` and ends after `VERIFY`, `COMPLETE`, or `ESCALATE`.
- `max_iterations` counts started iterations.
- `max_tool_calls` counts calls handed to `ToolExecutor`, including denied and failed calls.
- `max_failures` counts malformed LLM responses and non-successful tool results. Permission denial
  and approval-required outcomes escalate immediately instead of consuming retries.
- Token accounting uses provider-reported `total_tokens`, or the safe sum of reported prompt and
  completion tokens when total is absent. Missing usage counts as zero and is marked unavailable;
  it is never estimated or invented.
- A known token total that would exceed the cumulative budget terminates before another external
  call.
- Cost is recorded only when a future injected authoritative cost source provides it. Phase 13
  does not estimate prices.

## Stagnation detection

After each decision and verification, the runtime computes a deterministic SHA-256 fingerprint of
an allowlisted canonical structure: action type, tool name, normalized argument shape, terminal
verification outcome, and stable tool error code. It never hashes prompts, raw LLM responses,
file content, stdout, or stderr.

If the same fingerprint fills `stagnation_window` consecutive progress observations, the runtime
returns `ESCALATED` with reason `STAGNATION_DETECTED`. This requires no extra LLM call.

## Timeout and cancellation

The entire run executes under one monotonic `asyncio.timeout`. Existing provider and tool timeouts
remain narrower inner boundaries.

On global timeout, the runtime records one terminal `TIMED_OUT` audit step and returns a bounded
`TIMED_OUT` result. On `asyncio.CancelledError`, it records `CANCELLED` using cancellation-resistant
audit cleanup and immediately re-raises cancellation. It never converts cancellation into a
normal failure and never closes injected providers, executors, sessions, or network clients.

## Audit model

Every started and terminal runtime step is sent to `RuntimeAuditRecorder` with allowlisted metadata:

- agent, run, project, task, and correlation identifiers;
- iteration and step;
- outcome and stable reason/error code;
- duration, tool-call count, failure count, and reported token count;
- action category and tool name when applicable.

Audit metadata excludes prompts, LLM responses, reasoning, tool arguments, tool output, filesystem
paths, environment values, provider errors, secrets, and task content.

Phase 13 adds a PostgreSQL adapter that appends `AuditEvent` records through the existing
append-only repository. The adapter never commits, rolls back, or closes the injected session.
An audit-start failure prevents the corresponding step. A terminal audit failure returns or raises
a sanitized runtime audit error rather than silently losing traceability.

## Error handling

All public failures use stable non-sensitive `RuntimeErrorCode` values. Provider exceptions,
validation details, raw responses, tool content, paths, and database messages are discarded before
crossing the runtime boundary.

Malformed LLM output increments the failure counter. If the remaining failure budget permits, the
next iteration begins from a safe metadata-only history entry; otherwise the run ends as `FAILED`.
There is no automatic repair prompt in V1.

Tool results are interpreted deterministically:

- `SUCCEEDED`: pass the bounded result to verification;
- `DENIED` with permission missing: terminal escalation;
- `DENIED` with approval required: terminal human escalation;
- `FAILED` or `TIMED_OUT`: increment failures, then verify only if budget remains;
- cancellation: propagate immediately.

## Testing strategy

Tests use the concrete `LLMLoopReasoner` with `FakeLLMProvider`, real strict response decoding, a
real `ToolExecutor` with deterministic fake tools and permission/audit collaborators, and a fake
runtime audit recorder. PostgreSQL integration tests use the real migrated database and append-only
audit repository.

Required scenarios:

1. completion on the first decision;
2. tool failure followed by a new corrective decision and success;
3. maximum iteration termination;
4. permission denial and approval-required escalation;
5. malformed LLM response with bounded failure behavior;
6. global timeout;
7. normal completion after tool verification;
8. stagnation escalation;
9. tool-call, failure, history, and token budget enforcement;
10. cancellation propagation and terminal audit;
11. no sensitive prompts, responses, arguments, or outputs in retained history or audit;
12. no duplicate provider or tool calls and no collaborator lifecycle ownership.

## Documentation and checklist

Add operator and developer documentation for the loop contract, budgets, audit content, terminal
states, and deliberate exclusions. Update only Phase 13 checkboxes after their corresponding tests
and implementation are complete. Leave every Phase 12 and Phase 14 checkbox unchanged.
