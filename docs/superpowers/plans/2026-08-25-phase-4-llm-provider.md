# Phase 4 LLM Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider-neutral asynchronous LLM contracts, a tested Ollama HTTP adapter, and a deterministic fake provider without implementing agent behavior or later provider routing.

**Architecture:** Core owns immutable request/response types, normalized errors, and the provider protocol. Infrastructure owns Ollama and fake implementations; callers never depend on Ollama-specific types. HTTP behavior is tested with `httpx.MockTransport`, so no test requires a running Ollama service.

**Tech Stack:** Python 3.12, Pydantic v2, `typing.Protocol`, httpx async client, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-25-phase-4-llm-provider-design.md`

## Global Constraints

- Implement Phase 4 only; do not add agents, provider routing, cloud gateways, tools, or Phase 5 behavior.
- Use English for code, comments, tests, commits, and new documentation.
- Observe every new behavioral test fail for the expected reason before production implementation.
- Tests must not connect to a real Ollama instance.
- PostgreSQL-backed repository tests continue to use real PostgreSQL through Alembic.
- Credentials must never enter core request/response objects, metadata, exceptions, or logs.
- Network duration, response bytes, generated tokens, and in-memory test history must be bounded.
- Providers perform no implicit retries or persistence.
- Do not commit or push until the user explicitly requests it.

---

### Task 1: Core LLM value objects

**Files:**
- Create: `core/llm/__init__.py`
- Create: `core/llm/types.py`
- Test: `tests/llm/__init__.py`
- Test: `tests/llm/test_types.py`

**Interfaces:**
- Produces: `LLMRole`, `LLMMessage`, `LLMRequest`, `LLMUsage`, `LLMModelMetadata`, and `LLMResponse`.
- All models use `ConfigDict(frozen=True, extra="forbid")`.

- [ ] **Step 1: Write failing tests for strict validation and immutability**

  Cover non-empty message content, non-empty messages, optional trimmed system prompt, temperature
  bounds `0.0..2.0`, positive `max_tokens`, non-negative usage values, forbidden extras, tuple
  normalization, and frozen instances. Expected values must be literal and independent of the
  production validators.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `.venv/bin/pytest tests/llm/test_types.py -q`

  Expected: collection/import failure because `core.llm` contracts do not exist.

- [ ] **Step 3: Implement the minimal Pydantic models**

  Use a local `LLMRole(StrEnum)` with `SYSTEM`, `USER`, and `ASSISTANT`. Use `Annotated` constraints
  and immutable defaults. Do not add provider configuration to `LLMRequest`.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/llm/test_types.py -q`

  Expected: all tests pass without warnings.

### Task 2: Provider protocol and normalized errors

**Files:**
- Create: `core/llm/provider.py`
- Create: `core/llm/errors.py`
- Modify: `core/llm/__init__.py`
- Test: `tests/llm/test_provider_contract.py`

**Interfaces:**
- Produces: runtime-checkable `LLMProvider` with `generate(LLMRequest) -> Awaitable[LLMResponse]`.
- Produces: `LLMProviderError`, `LLMConfigurationError`, `LLMTimeoutError`,
  `LLMConnectionError`, and `LLMResponseError`.

- [ ] **Step 1: Write failing protocol and safe-error tests**

  Prove a structural async implementation satisfies the protocol. Prove normalized errors retain a
  provider identifier and optional status code while their public string contains only the supplied
  safe message.

- [ ] **Step 2: Run focused tests and verify RED**

  Run: `.venv/bin/pytest tests/llm/test_provider_contract.py -q`

  Expected: import failure for the missing protocol/errors.

- [ ] **Step 3: Implement the minimal protocol and error hierarchy**

  Keep the protocol free of constructors and infrastructure imports. Store only safe structured
  fields on errors.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/llm/test_provider_contract.py -q`

### Task 3: Deterministic fake provider

**Files:**
- Create: `infrastructure/llm/fake.py`
- Modify: `infrastructure/llm/__init__.py`
- Test: `tests/llm/test_fake_provider.py`

**Interfaces:**
- Consumes: core LLM contracts.
- Produces: `FakeLLMProvider(responses=(), error=None, max_history=100)` and async `generate()`.
- Exposes recorded requests as an immutable tuple.

- [ ] **Step 1: Write failing behavior tests**

  Prove queued responses are returned in order, requests are recorded, configured errors propagate,
  response-queue or history exhaustion raises a normalized response error, and the class structurally satisfies
  `LLMProvider`.

- [ ] **Step 2: Run focused tests and verify RED**

  Run: `.venv/bin/pytest tests/llm/test_fake_provider.py -q`

- [ ] **Step 3: Implement the minimal in-memory provider**

  Use a deque internally, append the immutable request before resolving the configured outcome, and
  never perform I/O.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/llm/test_fake_provider.py -q`

### Task 4: Ollama request and response translation

**Files:**
- Modify: `pyproject.toml`
- Create: `infrastructure/llm/ollama.py`
- Test: `tests/llm/test_ollama_provider.py`

**Interfaces:**
- Consumes: core LLM contracts and `httpx.AsyncClient`.
- Produces: `OllamaLLMProvider(base_url, model, timeout_seconds, max_response_bytes, client=None)`.
- Calls: `POST {base_url}/api/chat` with `stream: false`.

- [ ] **Step 1: Move httpx into runtime dependencies**

  Keep one `httpx>=0.27` declaration under project dependencies and remove its duplicate from dev
  dependencies. Refresh the environment using `make install` after the manifest change.

- [ ] **Step 2: Write a failing successful-generation test**

  Use `httpx.MockTransport` with a complete Ollama response fixture. Assert the real provider output
  and inspect the received HTTP request to prove system-message precedence, caller-message order,
  model selection, non-streaming mode, temperature, and `num_predict` translation.

- [ ] **Step 3: Run the focused test and verify RED**

  Run: `.venv/bin/pytest tests/llm/test_ollama_provider.py -q`

- [ ] **Step 4: Implement minimal request/response translation**

  Parse `message.content`, `model`, `done_reason`, `prompt_eval_count`, `eval_count`, and sanitized
  `details`. Derive total tokens only when both component counts are available.

- [ ] **Step 5: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/llm/test_ollama_provider.py -q`

- [ ] **Step 6: Add RED tests for omitted optional values**

  Prove omitted request options are not sent and absent token counters produce `usage=None` rather
  than fabricated zeros.

- [ ] **Step 7: Implement optional-value behavior and verify GREEN**

  Run: `.venv/bin/pytest tests/llm/test_ollama_provider.py -q`

### Task 5: Ollama failure normalization and lifecycle

**Files:**
- Modify: `infrastructure/llm/ollama.py`
- Modify: `tests/llm/test_ollama_provider.py`

**Interfaces:**
- Produces safe normalized failures while preserving `asyncio.CancelledError`.

- [ ] **Step 1: Add parameterized RED tests for provider failures**

  Cover `httpx.TimeoutException`, `httpx.ConnectError`, HTTP 4xx/5xx with a secret-bearing body,
  oversized streamed responses, invalid JSON, missing message, non-string content, and cancellation.
  Assert secret text is absent from normalized errors and prove no request is retried.

- [ ] **Step 2: Run focused tests and verify RED**

  Run: `.venv/bin/pytest tests/llm/test_ollama_provider.py -q`

- [ ] **Step 3: Implement narrow exception translation**

  Catch timeout and connection exceptions separately, map HTTP/malformed payloads to
  `LLMResponseError`, and avoid catching `BaseException` so cancellation propagates.

- [ ] **Step 4: Add and satisfy client-ownership tests**

  Prove injected clients remain open and internally created clients close after a request. Run the
  focused test file until pristine GREEN.

### Task 6: Environment configuration

**Files:**
- Modify: `core/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ollama_base_url: str`, `ollama_model: str`, `ollama_timeout_seconds: float`, and
  `ollama_max_response_bytes: int` on `Settings`.

- [ ] **Step 1: Write RED tests for defaults, overrides, and invalid timeout**

  Instantiate settings with `_env_file=None` and literal environment-shaped keyword values to avoid
  coupling tests to the developer's `.env` file.

- [ ] **Step 2: Run focused tests and verify RED**

  Run: `.venv/bin/pytest tests/test_config.py -q`

- [ ] **Step 3: Implement constrained settings and placeholders**

  Default to `http://localhost:11434`, a documented local model name, and a positive timeout. Add no
  credential field for Ollama.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `.venv/bin/pytest tests/test_config.py -q`

### Task 7: Documentation and Phase 4 acceptance

**Files:**
- Create: `docs/llm-providers.md`
- Create: `docs/adr/0004-provider-neutral-llm-boundary.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents core usage, Ollama configuration, fake usage, safe error handling, and future adapters.

- [ ] **Step 1: Document the verified implementation**

  Include a minimal async consumer example that imports only `core.llm` contracts, an Ollama setup
  example at the infrastructure boundary, all environment variables, error behavior, and an explicit
  statement that gateway/cloud providers and routing remain future work.

- [ ] **Step 2: Record the architectural decision**

  Explain why the core uses a protocol and normalized types, why Ollama uses HTTP instead of its SDK,
  and how future base-URL/API-key providers remain isolated.

- [ ] **Step 3: Update only verified Phase 4 checkboxes**

  Do not modify Phase 5 or later sections. Update the repository status and commands where the actual
  implementation changed them.

### Task 8: Complete verification and review

**Files:**
- Review all Phase 4 changes.

**Interfaces:**
- Produces a verified Phase 4 branch ready for user-authorized commit and push.

- [ ] **Step 1: Run focused and complete test suites**

  Run:

  ```text
  .venv/bin/pytest tests/llm tests/test_config.py -q
  TEST_POSTGRES_PORT=55432 .venv/bin/pytest -q
  ```

- [ ] **Step 2: Run static quality gates**

  Run:

  ```text
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/mypy .
  git diff --check
  ```

- [ ] **Step 3: Validate the containerized application**

  Rebuild the API image, upgrade Alembic to head, run `alembic check`, and verify `/health`. Ollama is
  not added to Docker Compose and is not required for API liveness.

- [ ] **Step 4: Run an independent code review**

  Resolve every Critical or Important finding through a new RED-GREEN cycle, then rerun all gates.

- [ ] **Step 5: Run a dedicated security and resource-efficiency review**

  Review secret handling, SSRF/trust boundaries, cancellation, response limits, client ownership,
  unbounded collections, duplicate requests, and accidental persistence. Resolve confirmed findings
  through RED-GREEN cycles.

- [ ] **Step 6: Report without committing automatically**

  List files, commands, tests, decisions, problems, and remaining work. Commit and push only after an
  explicit user instruction.
