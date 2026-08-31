# Loop Engineering V1

Phase 13 introduces the first controlled autonomous loop for one agent. It is provider-neutral and
does not create a DeveloperAgent, coordinate multiple agents, or implement MCP.

## State machine

```text
OBSERVE -> PLAN -> DECIDE
  COMPLETE -> REPORT -> COMPLETED
  ESCALATE -> REPORT -> ESCALATED
  TOOL_CALL -> ACT -> VERIFY
    CONTINUE -> next iteration
    COMPLETE -> REPORT -> COMPLETED
    ESCALATE -> REPORT -> ESCALATED
```

`AgentRuntime.run()` accepts an immutable `RuntimeTask` and an existing `ToolExecutionContext`.
Every action goes exactly once through the central `ToolExecutor`; registry validation, declared
capabilities, persisted permissions, approval gates, timeouts, output limits, and tool auditing
therefore remain mandatory. The runtime exposes no direct shell, filesystem, Git, or network path.

## Mandatory limits

| Limit | Accepted range | Meaning |
| --- | ---: | --- |
| `max_iterations` | 1–100 | Iterations that may start |
| `timeout_seconds` | >0–3,600 | Monotonic deadline for the whole run |
| `max_tool_calls` | 0–1,000 | Calls handed to `ToolExecutor`, including failures |
| `max_failures` | 0–100 | Malformed reasoning and unsuccessful tools |
| `max_tokens` | 1–10,000,000 | Cumulative provider-reported tokens |
| `max_history_entries` | 1–1,000 | Metadata-only entries retained in memory |
| `stagnation_window` | 2–20 | Equal consecutive progress fingerprints |
| `max_step_tokens` | 1–131,072 | Maximum generation configured per LLM request |

Token usage is never estimated. The runtime uses the provider's authoritative total, or its
reported prompt-plus-completion total. Missing usage remains zero and makes `usage_available`
false. An exhausted known budget prevents the next external call. Phase 13 does not estimate cost.

## Termination and failure behavior

- `COMPLETED`: acceptance was reported complete.
- `ESCALATED`: the agent escalated, permission was denied, approval is required, or the loop
  stagnated.
- `LIMIT_REACHED`: an iteration, tool-call, or token budget was exhausted.
- `TIMED_OUT`: the global deadline expired.
- `FAILED`: the failure limit, audit boundary, or structured-output boundary failed closed.

There are no retries inside reasoning or tool operations. A malformed response or failed tool can
only lead to another attempt through a new bounded iteration. Permission denial and approval
requirements escalate immediately.

The public result retains only counters, stable classifications, duration, and bounded
metadata-only history. Prompts, responses, rationale, arguments, tool output, paths, and raw errors
are excluded. A report is generated for ordinary terminal states but its text is deliberately not
persisted in `RuntimeResult` during Phase 13.

## Stagnation, audit, and lifecycle

The stagnation detector keeps at most `stagnation_window` SHA-256 digests. A digest covers only the
action category, tool name, recursive argument key/type shape, verification outcome, and stable
tool error code. It never hashes or stores argument values or content.

Each step emits started and terminal `RuntimeAuditRecord` values. The PostgreSQL adapter validates
the persisted agent/run/task/project scope and appends an `AGENT_RUNTIME_STEP` `AuditEvent` with
allowlisted identifiers, counters, outcomes, actions, reasons, tool names, and error
classifications. It never commits, rolls back, or closes the caller's session. This guarantee is
application-level; database-level hardening is deferred.

The global timeout cancels active inner work. External cancellation is propagated after staging a
prevalidated cancellation event through a dedicated non-blocking recorder method. The production
adapter performs no query, flush, network I/O, or thread handoff on this path. The runtime never
closes injected providers, executors, sessions, or network clients.

## Deliberate exclusions

Phase 12 MCP remains unimplemented. Phase 13 adds no multi-agent coordination, DeveloperAgent,
memory, reputation, cost estimation, provider routing, recursive loop, or frontend.

## Focused verification

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/runtime tests/database/test_runtime_audit.py -q
```
