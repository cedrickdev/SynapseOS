# Phase 5 Agent Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, provider-neutral runtime agent that turns four explicit LLM calls into validated `Observation`, `Plan`, `Decision`, and `AgentReport` values without adding execution tools or an autonomous loop.

**Architecture:** `core.agents` owns immutable runtime values, safe structured-output decoding, and an `Agent` that depends only on `core.llm.LLMProvider`. The runtime profile declares permission, tool, and skill identifiers but cannot resolve or execute them. Successful calls retain only bounded, non-sensitive model-usage metadata in memory.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, existing provider-neutral LLM contract, pytest, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-5-agent-core-design.md`

## Global Constraints

- Implement Phase 5 only; do not add a Tool Registry, Skills Registry, permission engine, shell, filesystem access, terminal, MCP, autonomous loop, or multi-agent behavior.
- Use English for code, comments, tests, commits, and documentation.
- Observe every behavioral test fail for the expected reason before writing production code.
- Use the existing `FakeLLMProvider`; tests must not make network calls or require Ollama.
- PostgreSQL-backed repository tests continue to use real PostgreSQL through Alembic, never `metadata.create_all()`.
- Each public agent operation performs exactly one LLM call with explicit `max_tokens` and no retry, repair request, fallback, or duplicate call.
- Prompts, subjects, objectives, structured outputs, and raw provider responses must never enter history, exceptions, logs, or persistence.
- All retained text, collections, generated tokens, and history are bounded.
- Provider errors and `asyncio.CancelledError` propagate unchanged.
- `skill_ids` are inert identifiers only; do not read external or project-local `SKILL.md` files before Phase 8.
- Do not update Phase 6 or later checkboxes.
- Do not merge branches or push without explicit user authorization.

---

### Task 1: Immutable agent profile and structured values

**Files:**
- Create: `tests/agents/__init__.py`
- Create: `tests/agents/test_types.py`
- Create: `core/agents/types.py`
- Modify: `core/agents/__init__.py`

**Interfaces:**
- Consumes: `core.enums.AgentSeniority`, `core.enums.AgentStatus`, `core.llm.LLMUsage`.
- Produces: `AgentProfile`, `Observation`, `Plan`, `Decision`, `AgentReport`, `AgentReportOutcome`, `AgentOperation`, and `AgentHistoryEntry`.
- All models use `ConfigDict(frozen=True, extra="forbid")`.

- [ ] **Step 1: Write failing profile tests**

  Add literal fixtures proving a valid profile normalizes identifier collections to immutable
  sets. Add parameterized failures for blank or malformed identifiers, more than 128 identifiers,
  a system prompt over 16,384 characters, autonomy outside `0..5`, scores outside `0..1`, unknown
  fields, and attempted mutation. A realistic mutation such as removing the autonomy constraint or
  accepting uppercase permission identifiers must fail at least one test.

  ```python
  profile = AgentProfile(
      id="backend-agent-03",
      name="Backend Agent 03",
      role="Backend Engineer",
      department="engineering",
      seniority=AgentSeniority.SENIOR,
      status=AgentStatus.AVAILABLE,
      system_prompt="Build verifiable backend changes.",
      autonomy_level=2,
      permission_ids={"git.read", "tests.execute"},
      tool_ids={"repository-search"},
      skill_ids={"generic-backend", "testing"},
      reputation_score=Decimal("0.91"),
      reliability_score=Decimal("0.93"),
  )
  assert profile.skill_ids == frozenset({"generic-backend", "testing"})
  ```

- [ ] **Step 2: Run the profile tests and verify RED**

  Run: `.venv/bin/pytest tests/agents/test_types.py -q`

  Expected: import failure because the Phase 5 types do not exist.

- [ ] **Step 3: Implement the minimal profile and shared constraints**

  In `core/agents/types.py`, define constrained aliases with `Annotated`, a strict identifier
  pattern `^[a-z0-9][a-z0-9._:-]{0,127}$`, and an internal immutable base model. Use field
  validators to reject blank bounded text and normalize identifier inputs to `frozenset[str]`.
  Use `Decimal` score fields with finite `0..1` constraints.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_types.py -q`

  Expected: all profile tests pass without warnings.

- [ ] **Step 5: Add failing structured-value tests**

  Cover tuple normalization, mandatory plan steps and success criteria, field and collection size
  limits, finite decision confidence, forbidden extras, frozen values, and the four report outcomes.
  Build expected tuples and enum values literally rather than with production helpers.

- [ ] **Step 6: Run the new tests and verify RED**

  Run: `.venv/bin/pytest tests/agents/test_types.py -q`

  Expected: failures for missing structured value classes or missing constraints.

- [ ] **Step 7: Implement the minimal structured values and history metadata**

  Add the exact fields and limits from the design. Define:

  ```python
  class AgentReportOutcome(StrEnum):
      SUCCEEDED = "SUCCEEDED"
      FAILED = "FAILED"
      BLOCKED = "BLOCKED"
      NEEDS_HUMAN = "NEEDS_HUMAN"


  class AgentOperation(StrEnum):
      OBSERVE = "OBSERVE"
      PLAN = "PLAN"
      DECIDE = "DECIDE"
      REPORT = "REPORT"
  ```

  `AgentHistoryEntry` contains only `operation`, timezone-aware `completed_at`, `provider`, `model`,
  and optional `usage`. Reject naive timestamps and blank provider/model identifiers.

- [ ] **Step 8: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_types.py -q`

- [ ] **Step 9: Export the public contract and commit**

  Export Phase 5 public types from `core/agents/__init__.py` using an explicit `__all__`.

  Run: `.venv/bin/ruff check core/agents tests/agents && .venv/bin/mypy core/agents tests/agents`

  Commit: `feat(agents): add immutable agent runtime types`

### Task 2: Strict and safe structured-output decoding

**Files:**
- Create: `tests/agents/test_structured_output.py`
- Create: `core/agents/errors.py`
- Create: `core/agents/structured_output.py`
- Modify: `core/agents/__init__.py`

**Interfaces:**
- Produces: `AgentError` and `AgentOutputValidationError(expected_type: str)`.
- Produces: `decode_structured_output(content: str, model_type: type[ModelT]) -> ModelT` where
  `ModelT` is bound to `pydantic.BaseModel`.

- [ ] **Step 1: Write failing valid-decoding and malformed-JSON tests**

  Prove a literal JSON object becomes the requested real Pydantic value. Prove blank content,
  ordinary prose, Markdown fences, trailing prose, arrays at the root, `NaN`, `Infinity`, and
  duplicate top-level data fail with `AgentOutputValidationError`.

  ```python
  result = decode_structured_output(
      '{"summary":"Repository inspected","facts":[],"uncertainties":[],"risks":[]}',
      Observation,
  )
  assert result.summary == "Repository inspected"
  ```

- [ ] **Step 2: Run decoder tests and verify RED**

  Run: `.venv/bin/pytest tests/agents/test_structured_output.py -q`

  Expected: import failure for the missing decoder and error.

- [ ] **Step 3: Implement strict JSON parsing and Pydantic validation**

  Call `json.loads()` once with `parse_constant` that raises `ValueError`, require `dict` at the
  root, and call `model_type.model_validate()`. Catch only JSON, value, and Pydantic validation
  failures and raise the safe normalized error with exception chaining suppressed from public
  output.

- [ ] **Step 4: Run decoder tests and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_structured_output.py -q`

- [ ] **Step 5: Add failing confidentiality tests**

  Use a unique secret marker in malformed content and invalid field values. Assert it is absent from
  `str(error)`, `repr(error)`, `error.args`, and every public error attribute. Assert the error
  exposes only a stable safe message and expected type name.

- [ ] **Step 6: Implement safe error fields and verify GREEN**

  `AgentOutputValidationError` stores only `expected_type`; it must not store the original exception,
  response content, parsed object, Pydantic error list, prompt, or provider metadata.

  Run: `.venv/bin/pytest tests/agents/test_structured_output.py -q`

- [ ] **Step 7: Run quality gates and commit**

  Run: `.venv/bin/ruff check core/agents tests/agents && .venv/bin/mypy core/agents tests/agents`

  Commit: `feat(agents): validate structured agent outputs safely`

### Task 3: Agent construction, observation, and bounded history

**Files:**
- Create: `tests/agents/conftest.py`
- Create: `tests/agents/test_agent_observe.py`
- Create: `core/agents/agent.py`
- Modify: `core/agents/__init__.py`

**Interfaces:**
- Consumes: `AgentProfile`, `Observation`, `AgentHistoryEntry`, `LLMProvider`, `LLMRequest`,
  `LLMMessage`, `LLMRole`, and `decode_structured_output()`.
- Produces: `Agent(profile, provider, max_history=100, max_tokens=2048)`.
- Produces: `async observe(subject: str) -> Observation` and immutable `history` snapshots.

- [ ] **Step 1: Add deterministic response fixtures and a failing observation test**

  Build complete `LLMResponse` fixtures with provider/model metadata and optional literal usage.
  Use the real `FakeLLMProvider`. Prove `observe()` returns a validated observation and inspect the
  fake's real recorded request to prove:

  - profile system prompt is supplied through `LLMRequest.system_prompt`;
  - exactly one user message is sent;
  - the subject appears once;
  - `max_tokens` is explicit;
  - there is exactly one provider request.

- [ ] **Step 2: Run the observation test and verify RED**

  Run: `.venv/bin/pytest tests/agents/test_agent_observe.py -q`

  Expected: import failure for the missing runtime `Agent`.

- [ ] **Step 3: Implement constructor validation and minimal `observe()`**

  Validate `max_history >= 1` and `1 <= max_tokens <= 131072`. Validate subject text before the
  call: non-blank and at most 32,768 characters. Build one bounded instruction that requests only
  the documented `Observation` JSON fields, call the provider once, then decode once.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_agent_observe.py -q`

- [ ] **Step 5: Add failing history tests**

  Prove successful calls append metadata, snapshots are tuples, capacity evicts the oldest entry,
  and entries contain no marker copied from subject, system prompt, raw response, or structured
  output. Verify a malformed output and provider error append no entry.

- [ ] **Step 6: Implement bounded metadata-only history**

  Use `deque[AgentHistoryEntry](maxlen=max_history)`. After successful decoding only, append an entry
  using `datetime.now(UTC)`, response provider/model, and usage. Do not store requests or responses
  on the runtime.

- [ ] **Step 7: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_agent_observe.py -q`

- [ ] **Step 8: Add failing error and cancellation tests**

  Prove a configured `LLMProviderError` is the same propagated instance and only one request was
  attempted. Use a small cancelling provider to raise `asyncio.CancelledError`; assert it propagates,
  history stays empty, and no second call occurs.

- [ ] **Step 9: Preserve propagation behavior and verify GREEN**

  Do not catch provider errors or `asyncio.CancelledError` around `provider.generate()`.

  Run: `.venv/bin/pytest tests/agents/test_agent_observe.py -q`

- [ ] **Step 10: Run quality gates and commit**

  Run: `.venv/bin/ruff check core/agents tests/agents && .venv/bin/mypy core/agents tests/agents`

  Commit: `feat(agents): add bounded observation runtime`

### Task 4: Planning, decision, and reporting operations

**Files:**
- Create: `tests/agents/test_agent_workflow.py`
- Modify: `core/agents/agent.py`

**Interfaces:**
- Produces: `async plan(observation: Observation, objective: str) -> Plan`.
- Produces: `async decide(observation: Observation, plan: Plan) -> Decision`.
- Produces: `async report(observation: Observation, plan: Plan, decision: Decision) -> AgentReport`.

- [ ] **Step 1: Write a failing deterministic planning test**

  Queue a complete plan response in `FakeLLMProvider`. Prove the validated return value, exactly one
  request, explicit `max_tokens`, one occurrence of the objective, and a user message containing the
  validated observation fields but no earlier raw prompt or provider response.

- [ ] **Step 2: Run the planning test and verify RED**

  Run: `.venv/bin/pytest tests/agents/test_agent_workflow.py::test_plan_returns_validated_plan_with_one_call -q`

- [ ] **Step 3: Implement minimal `plan()` and verify GREEN**

  Validate non-blank objective at most 8,192 characters, serialize the validated observation with
  `model_dump(mode="json")`, call the provider once, decode `Plan`, then append a `PLAN` history
  event.

  Run: `.venv/bin/pytest tests/agents/test_agent_workflow.py::test_plan_returns_validated_plan_with_one_call -q`

- [ ] **Step 4: Write a failing deterministic decision test**

  Prove `decide()` includes only the supplied validated observation and plan, validates confidence,
  returns the real `Decision`, records `DECIDE`, and performs one call.

- [ ] **Step 5: Implement minimal `decide()` and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_agent_workflow.py::test_decide_returns_validated_decision_with_one_call -q`

- [ ] **Step 6: Write a failing deterministic report test**

  Prove `report()` includes only the supplied validated values, accepts the four report outcomes,
  returns `AgentReport`, records `REPORT`, and performs one call.

- [ ] **Step 7: Implement minimal `report()` and verify GREEN**

  Run: `.venv/bin/pytest tests/agents/test_agent_workflow.py::test_report_returns_validated_report_with_one_call -q`

- [ ] **Step 8: Add parameterized failure and boundary tests**

  Across all three operations, prove malformed output is safe, provider errors are not retried,
  cancellation propagates, history updates only on success, and the operation instruction plus
  serialized values remain within the limits implied by validated fields. Prove an oversized or
  blank objective fails before the fake records a request.

- [ ] **Step 9: Refactor shared one-call generation without changing behavior**

  Extract private request construction and successful history recording only after all focused
  tests are green. Keep the target output type and operation explicit; do not add loops, retries,
  dynamic method dispatch, prompt memory, or provider lifecycle ownership.

- [ ] **Step 10: Run agent tests and commit**

  Run: `.venv/bin/pytest tests/agents -q`

  Run: `.venv/bin/ruff check core/agents tests/agents && .venv/bin/mypy core/agents tests/agents`

  Commit: `feat(agents): add structured agent operations`

### Task 5: Phase 5 documentation and repository acceptance

**Files:**
- Create: `docs/agent-core.md`
- Create: `docs/adr/0005-agent-runtime-boundary.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents the runtime API, safe composition with `FakeLLMProvider` or an injected real provider,
  resource ownership, bounded history, safe failures, and Phase 8 `SKILL.md` boundary.

- [ ] **Step 1: Write usage and architecture documentation**

  Document one complete example that constructs `AgentProfile`, injects a provider, and calls one
  method. State explicitly that the runtime does not execute tools, load skills, own provider
  clients, retry, persist prompts/responses, or run autonomously.

- [ ] **Step 2: Record ADR 0005**

  Record the accepted decision to keep runtime agents separate from persistence models and to use
  strict one-call structured LLM operations with metadata-only bounded history. Include rejected
  alternatives: binding runtime behavior to SQLAlchemy and introducing an actor/autonomous loop.

- [ ] **Step 3: Update repository guidance and Phase 5 checkboxes only**

  Update status and commands in README/`AGENTS.md`. Check a Phase 5 item only when its implementation
  and direct test are complete. Keep every Phase 6 and later checkbox unchanged. The three negative
  checklist statements remain checked only as verified exclusions, consistent with earlier phase
  checklist practice.

- [ ] **Step 4: Run focused and complete automated gates**

  Run: `.venv/bin/pytest tests/agents -q`

  Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest -q`

  Run: `.venv/bin/ruff check .`

  Run: `.venv/bin/ruff format --check .`

  Run: `.venv/bin/mypy .`

  Run: `git diff --check`

  Expected: all commands pass without warnings or errors.

- [ ] **Step 5: Validate deployment-adjacent invariants**

  Run the existing Docker build, Alembic upgrade/current/check sequence against the real PostgreSQL
  service, API health check, and secret scan. Phase 5 adds no migration, so Alembic must report the
  existing Phase 2 head without drift.

- [ ] **Step 6: Perform security and final code reviews**

  Review the complete Phase 5 diff for prompt/response leakage, unbounded retention, duplicate LLM
  calls, cancellation swallowing, mutable profile escalation, accidental capability execution,
  infrastructure imports in core, and any Phase 6+ implementation. Resolve every Critical and
  Important finding through RED-GREEN-REFACTOR.

- [ ] **Step 7: Commit documentation and verified checklist state**

  Commit: `docs(agents): document Phase 5 agent core`

- [ ] **Step 8: Re-run final gates and inspect branch state**

  Re-run pytest, Ruff, format check, mypy, `git diff --check`, and `git status --short --branch`.
  Do not claim completion, push, or open a PR until all results are current and clean.
