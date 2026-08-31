# Phase 13 Loop Engineering V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one bounded, audited, provider-neutral autonomous agent loop that can select and execute existing secured tools without implementing multi-agent behavior.

**Architecture:** Immutable contracts and ports live in `core/runtime`; `LLMLoopReasoner` performs strict one-shot structured generations; `AgentRuntime` owns the non-recursive state machine and budgets; SQLAlchemy only implements the audit port. Existing `ToolExecutor` remains the exclusive action boundary.

**Tech Stack:** Python 3.12, asyncio, Pydantic v2, existing LLM/tool/permission contracts, SQLAlchemy 2, PostgreSQL 16, pytest, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-28-phase-13-loop-engineering-v1-design.md`

## Global Constraints

- Implement Phase 13 only; leave all Phase 12 and Phase 14+ checkboxes unchanged.
- One agent only; no orchestration, delegation, scheduler, event bus, role-specific agent, or multi-agent state.
- No free-form command, permission bypass, implicit retry, recursion, fallback provider, or duplicate tool call.
- Every external call is bounded; the run has one monotonic global timeout.
- Cancellation propagates after cancellation-resistant terminal audit cleanup.
- Never persist prompts, LLM responses, reasoning, tool arguments/output, paths, environment values, or provider/database errors.
- Injected providers, executors, sessions, and network clients are never closed by the runtime.
- Tests use `FakeLLMProvider`; database tests use real PostgreSQL migrated by Alembic.
- Apply strict RED → GREEN → REFACTOR TDD and commit each independently reviewable task.

---

## File structure

- `core/runtime/types.py` — immutable limits, task, step, decision, verification, audit, and result values.
- `core/runtime/errors.py` — stable sanitized runtime error codes and exceptions.
- `core/runtime/audit.py` — persistence-neutral runtime audit recorder protocol.
- `core/runtime/reasoner.py` — reasoner protocol and strict LLM-backed implementation.
- `core/runtime/stagnation.py` — bounded allowlisted progress fingerprint window.
- `core/runtime/runtime.py` — iterative one-agent state machine and budget enforcement.
- `core/runtime/__init__.py` — explicit public Phase 13 API.
- `infrastructure/runtime/audit.py` — SQLAlchemy append-only audit adapter.
- `infrastructure/runtime/__init__.py` — infrastructure exports.
- `tests/runtime/` — contracts, reasoner, loop, security, and cancellation tests.
- `tests/database/test_runtime_audit.py` — migrated PostgreSQL audit integration.
- `docs/runtime.md` — operator/developer contract and exclusions.

### Task 1: Immutable runtime contracts

**Files:**
- Create: `core/runtime/types.py`
- Create: `core/runtime/errors.py`
- Modify: `core/runtime/__init__.py`
- Create: `tests/runtime/__init__.py`
- Create: `tests/runtime/test_types.py`

**Interfaces:**
- Produces: `RuntimeLimits`, `RuntimeTask`, `RuntimeStep`, `RuntimeAction`, `RuntimeObservation`, `RuntimePlan`, `RuntimeDecision`, `RuntimeVerification`, `RuntimeTerminalStatus`, `RuntimeTerminalReason`, `RuntimeHistoryEntry`, `RuntimeReport`, `RuntimeResult`, `ReasonerOutput[T]`, `RuntimeErrorCode`, `RuntimeError`.
- Consumes: existing `JsonValue`, `ToolErrorCode`, and UUID/Pydantic primitives.

- [ ] **Step 1: Write strict failing contract tests**

Assert exact enum values, frozen models, forbidden extras, copied JSON arguments, finite numeric
limits, bounded criteria/history, cross-field decision rules, truthful terminal status/reason pairs,
and combined constraints such as `stagnation_window <= max_history_entries`.

```python
def test_tool_decision_requires_name_and_arguments() -> None:
    decision = RuntimeDecision(
        action=RuntimeAction.TOOL_CALL,
        tool_name="fake_read",
        arguments={"path": "README.md"},
        rationale="Inspect the bounded target.",
        confidence=0.8,
    )
    assert decision.tool_name == "fake_read"
    with pytest.raises(ValidationError):
        RuntimeDecision(
            action=RuntimeAction.COMPLETE,
            tool_name="fake_read",
            arguments={},
            rationale="Invalid terminal decision.",
            confidence=0.8,
        )
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/runtime/test_types.py -q`
Expected: collection fails because Phase 13 runtime contracts do not exist.

- [ ] **Step 3: Implement minimal immutable models and safe errors**

Use `ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)`, strict validators, bounded
collections, finite fields, and recursive JSON copying. Define the exact terminal statuses and
reasons from the approved spec; do not add future phases.

- [ ] **Step 4: Verify GREEN and static quality**

Run: `.venv/bin/pytest tests/runtime/test_types.py -q`
Run: `.venv/bin/ruff check core/runtime tests/runtime`
Run: `.venv/bin/mypy core/runtime tests/runtime`
Expected: all pass without warnings.

- [ ] **Step 5: Commit**

```bash
git add core/runtime tests/runtime
git commit -m "feat(runtime): define bounded loop contracts"
```

### Task 2: Strict one-shot LLM reasoner

**Files:**
- Create: `core/runtime/reasoner.py`
- Modify: `core/runtime/__init__.py`
- Create: `tests/runtime/conftest.py`
- Create: `tests/runtime/test_reasoner.py`

**Interfaces:**
- Produces: `LoopReasoner` protocol and `LLMLoopReasoner(provider, *, system_prompt, max_step_tokens)`.
- Produces async methods `observe`, `plan`, `decide`, `verify`, and `report`, each accepting the exact immutable runtime values from Task 1 and returning `ReasonerOutput[the_expected_type]`.
- Consumes: `LLMProvider`, `LLMRequest`, `LLMResponse`, `decode_structured_output`.

- [ ] **Step 1: Write RED tests with `FakeLLMProvider`**

Queue exact `LLMResponse` objects and assert each operation sends one request, uses the configured
`max_tokens`, validates one exact JSON object, returns its typed model, and records only returned
usage metadata. Assert malformed JSON, duplicate keys, extras, invalid tool arguments, and provider
failure produce sanitized `RuntimeError` values without a second provider call.

```python
async def test_decide_decodes_one_closed_tool_action(fake_response: LLMResponse) -> None:
    provider = FakeLLMProvider(responses=[fake_response])
    reasoner = LLMLoopReasoner(provider, system_prompt="Bounded runtime.", max_step_tokens=512)
    decision = await reasoner.decide(task, observation, plan, ())
    assert decision.action is RuntimeAction.TOOL_CALL
    assert len(provider.requests) == 1
    assert provider.requests[0].max_tokens == 512
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/runtime/test_reasoner.py -q`
Expected: fails because `LoopReasoner` and `LLMLoopReasoner` are absent.

- [ ] **Step 3: Implement bounded prompts and strict decoding**

Keep each prompt constant plus bounded JSON serialization of typed inputs. Never include prior raw
responses. Store no request/response history in the reasoner. Count usage from `total_tokens`, or
safe prompt/completion sum, and expose whether usage was reported.

- [ ] **Step 4: Verify GREEN and no duplicate calls**

Run: `.venv/bin/pytest tests/runtime/test_reasoner.py tests/llm tests/agents/test_structured_output.py -q`
Expected: all pass, malformed responses make exactly one provider request.

- [ ] **Step 5: Commit**

```bash
git add core/runtime/reasoner.py core/runtime/__init__.py tests/runtime
git commit -m "feat(runtime): add structured loop reasoner"
```

### Task 3: Runtime audit contract and PostgreSQL adapter

**Files:**
- Create: `core/runtime/audit.py`
- Create: `infrastructure/runtime/__init__.py`
- Create: `infrastructure/runtime/audit.py`
- Modify: `core/runtime/__init__.py`
- Create: `tests/runtime/test_audit_contract.py`
- Create: `tests/database/test_runtime_audit.py`

**Interfaces:**
- Produces: `RuntimeAuditStep`, `RuntimeAuditOutcome`, `RuntimeAuditRecord`, and `RuntimeAuditRecorder.record(record) -> None`.
- Produces: `SQLAlchemyRuntimeAuditRecorder(session: Session)`.
- Consumes: existing `AuditEvent`, `AuditEventRepository`, scope entities, and caller-owned `Session`.

- [ ] **Step 1: Write RED unit and real-PostgreSQL tests**

Assert one append-only `AuditEvent` per runtime step with `event_type="AGENT_RUNTIME_STEP"`,
`action="execute_agent_loop"`, agent/project/task/run/correlation scope, allowlisted counters, stable
outcome/reason, and no prompt, response, rationale, tool arguments/output, paths, or secret markers.
Assert forged scope and detached session fail safely. Assert recorder never commits, rolls back, or
closes the session.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/runtime/test_audit_contract.py -q`
Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_runtime_audit.py -q`
Expected: fails because runtime audit contracts and adapter are absent.

- [ ] **Step 3: Implement append-only sanitized recording**

Validate exact scope using the same `AgentRun -> Agent -> Task -> Project` relationship as tool
audit. Add and flush one `AuditEvent`; do not own the transaction. Map exceptions to
`RuntimeErrorCode.AUDIT_FAILED` and erase raw tracebacks/messages.

- [ ] **Step 4: Verify GREEN and append-only guard compatibility**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/database/test_runtime_audit.py tests/database/test_append_only.py -q`
Expected: all pass with no migration because `AuditEvent` already supports the data.

- [ ] **Step 5: Commit**

```bash
git add core/runtime/audit.py core/runtime/__init__.py infrastructure/runtime tests/runtime/test_audit_contract.py tests/database/test_runtime_audit.py
git commit -m "feat(runtime): audit bounded loop steps"
```

### Task 4: Deterministic stagnation detector

**Files:**
- Create: `core/runtime/stagnation.py`
- Modify: `core/runtime/__init__.py`
- Create: `tests/runtime/test_stagnation.py`

**Interfaces:**
- Produces: `StagnationDetector(window: int)` with `observe(decision, verification_or_none) -> bool` and immutable `size`.
- Consumes: `RuntimeDecision`, `RuntimeVerification`, stable `ToolErrorCode` only.

- [ ] **Step 1: Write RED behavior and secrecy tests**

Assert identical allowlisted progress shapes trigger only when the entire consecutive window is
full; changed action/tool/argument shape/outcome resets the run; values of arguments, rationale,
tool output, and secret markers never appear in the retained fingerprint state.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/runtime/test_stagnation.py -q`
Expected: fails because `StagnationDetector` is absent.

- [ ] **Step 3: Implement canonical SHA-256 fingerprints**

Canonicalize only action, tool name, recursively sorted argument key/type shape, verification
outcome, and stable tool error code. Retain a deque of at most `window` digests.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/pytest tests/runtime/test_stagnation.py -q`
Expected: all pass; no raw values are retained.

- [ ] **Step 5: Commit**

```bash
git add core/runtime/stagnation.py core/runtime/__init__.py tests/runtime/test_stagnation.py
git commit -m "feat(runtime): detect bounded loop stagnation"
```

### Task 5: Bounded one-agent runtime state machine

**Files:**
- Create: `core/runtime/runtime.py`
- Modify: `core/runtime/__init__.py`
- Create: `tests/runtime/fakes.py`
- Create: `tests/runtime/test_runtime.py`

**Interfaces:**
- Produces: `AgentRuntime(reasoner, tool_executor, audit_recorder, limits)`.
- Produces: `async run(task: RuntimeTask, context: ToolExecutionContext) -> RuntimeResult`.
- Consumes: Tasks 1–4 plus existing `ToolExecutor.execute()` and `ToolResult`.

- [ ] **Step 1: Write RED scenario tests**

Using concrete `LLMLoopReasoner(FakeLLMProvider(...))`, real `ToolExecutor`, deterministic fake
tools/permissions/tool audit, and recording runtime audit, cover:

- first-decision completion with zero tool calls;
- one failed tool result followed by a corrective new iteration and successful verification;
- normal completion after one successful tool result;
- permission denial and approval-required immediate escalation;
- malformed LLM output bounded by `max_failures`;
- `max_iterations`, `max_tool_calls`, known token budget, and stagnation termination;
- exactly one report call for normal terminal states;
- no duplicate provider/tool calls.

```python
result = asyncio.run(runtime.run(task, context))
assert result.status is RuntimeTerminalStatus.COMPLETED
assert result.iterations == 1
assert result.tool_calls == 1
assert FakeTool.calls == 1
assert len(provider.requests) == 5
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/runtime/test_runtime.py -q`
Expected: fails because `AgentRuntime` is absent.

- [ ] **Step 3: Implement the iterative state machine**

Use `for iteration in range(1, max_iterations + 1)` inside one global timeout. Audit every stage
before/after external work. Check deadline and budgets before every reasoner/tool call. Append only
safe bounded `RuntimeHistoryEntry` metadata. Route every action through `ToolExecutor`; interpret
status deterministically; never invoke the same decision twice.

- [ ] **Step 4: Verify GREEN and compatibility**

Run: `.venv/bin/pytest tests/runtime/test_runtime.py tests/tools/test_executor.py tests/agents -q`
Expected: all pass without changing existing tool or agent semantics.

- [ ] **Step 5: Commit**

```bash
git add core/runtime/runtime.py core/runtime/__init__.py tests/runtime
git commit -m "feat(runtime): execute bounded one-agent loops"
```

### Task 6: Timeout, cancellation, and adversarial hardening

**Files:**
- Modify: `core/runtime/runtime.py`
- Create: `tests/runtime/test_runtime_safety.py`

**Interfaces:**
- Strengthens `AgentRuntime.run()` without changing its public signature.

- [ ] **Step 1: Write RED timeout and cancellation tests**

Use blocking async reasoner/tool collaborators to prove global timeout returns `TIMED_OUT`, nested
tool timeout remains a tool observation, cancellation is immediately propagated, repeated
cancellation cannot interrupt terminal audit cleanup, and injected collaborators expose no runtime-
owned `close()` call. Verify audit failures are sanitized and never silently ignored.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/runtime/test_runtime_safety.py -q`
Expected: intended timeout/cancellation/audit assertions fail before hardening.

- [ ] **Step 3: Implement cancellation-resistant terminal audit**

Stage the finite cancellation audit through a dedicated prevalidated recorder method that performs
no query, flush, network I/O, or thread handoff, then re-raise the original cancellation. Keep
global timeout distinct from inner tool/provider failures. Do not add sleeps, retries, or resource
ownership.

- [ ] **Step 4: Add data-leak and finite-history assertions**

Place unique markers in task content, system prompt, malformed response, tool arguments/output,
workspace path, and provider error. Assert none appear in `RuntimeResult`, history, audit records,
exception strings, or metadata. Assert retained history never exceeds `max_history_entries`.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/runtime/test_runtime_safety.py tests/runtime/test_runtime.py -q`
Run: `.venv/bin/ruff check core/runtime tests/runtime`
Run: `.venv/bin/mypy core/runtime tests/runtime`
Expected: all pass without warnings.

```bash
git add core/runtime/runtime.py tests/runtime/test_runtime_safety.py
git commit -m "test(runtime): harden loop safety boundaries"
```

### Task 7: Documentation, checklist, and full verification

**Files:**
- Create: `docs/runtime.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents the completed public Phase 13 behavior; adds no runtime API.

- [ ] **Step 1: Document the implemented runtime**

Describe the state machine, immutable inputs/results, terminal statuses, exact budgets, token
accounting, stagnation fingerprints, tool/permission path, audit allowlist, timeout/cancellation,
configuration if introduced, operational limits, and Phase 12/14+ exclusions. Keep all code terms
and comments in English.

- [ ] **Step 2: Update only genuinely completed Phase 13 checkboxes**

Mark each Phase 13 guardrail complete only after its corresponding test passes. Do not change Phase
12 or Phase 14. Add no claim of cost accounting unless an authoritative injected cost value exists.

- [ ] **Step 3: Run focused and full quality gates**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/runtime tests/database/test_runtime_audit.py -q`
Run: `make check`
Run: `.venv/bin/ruff format --check .`
Run: `git diff --check phase-11/secure-command-runner..HEAD`
Expected: every command passes with pristine output.

- [ ] **Step 4: Validate Docker and migrations**

Run: `docker compose build api`
Run: `docker compose up -d db api`
Run: `docker compose exec -T api alembic current`
Run: `curl --fail --silent http://localhost:8000/health`
Expected: image builds, services are healthy, Alembic remains at the existing head unless a reviewed
audit schema need was discovered, and health returns `{"status":"ok"}`.

- [ ] **Step 5: Independent review and remediation**

Request a read-only correctness/security review against `phase-11/secure-command-runner`. Reproduce
every valid finding with a failing test, fix it in TDD order, rerun the complete gates, and obtain a
merge-ready verdict.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/runtime.md README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md
git commit -m "docs(runtime): complete Phase 13 guidance"
```

- [ ] **Step 7: Push and create the stacked PR**

Push `phase-13/loop-engineering-v1` and create a PR whose base is
`phase-11/secure-command-runner`. Do not merge it and do not start Phase 14.
