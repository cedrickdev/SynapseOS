# Phase 4 LLM Provider Design

## Status

Approved on 2026-08-25.

## Goal

Introduce a provider-neutral asynchronous LLM contract and an Ollama adapter without adding agent
runtime behavior. Consumers must depend only on core contracts so API gateways and cloud providers
can be added later without changing consumer code.

## Scope

Phase 4 includes:

- immutable request, message, response, usage, and model metadata types;
- an asynchronous `LLMProvider` protocol;
- normalized provider errors;
- an Ollama HTTP adapter;
- a deterministic fake provider;
- environment-driven Ollama configuration;
- unit tests that never require a running Ollama instance;
- usage documentation and an ADR.

Phase 4 excludes:

- cloud or API-gateway provider implementations;
- provider selection or routing;
- retries, fallback chains, budgets, rate limiting, or model scoring;
- prompt templates, agent behavior, tools, skills, memory, and orchestration;
- persistence of prompts or responses.

## Operational Invariants

Phase 4 is designed for a resource-conscious multinational deployment even though it introduces
only one local provider:

- memory, response size, request duration, and generated tokens are explicitly bounded;
- providers perform no implicit retry, fallback, or duplicate request that could multiply cost;
- prompts, response bodies, credentials, and headers never appear in normalized errors or logs;
- provider-specific metadata uses an allowlist rather than forwarding arbitrary payloads;
- caller-owned HTTP clients are never closed or mutated by an adapter;
- provider-owned network resources have an explicit asynchronous close operation;
- cancellation propagates immediately and is never reported as an ordinary provider failure;
- no request or response is persisted by the provider layer.

## Architectural Boundary

The core owns the vocabulary used by all callers:

```text
Consumer -> core.llm.LLMProvider -> infrastructure adapter -> external model service
```

`core/llm` must not import `httpx`, Ollama, or any infrastructure package. Infrastructure adapters
may import core contracts. Consumers must never import an Ollama-specific request or response type.

Future adapters may represent OpenAI-compatible gateways, direct cloud APIs, or local runtimes.
They will implement the same protocol and translate provider-specific payloads at the infrastructure
boundary. A future provider may accept a base URL and API key in its own configuration, but API keys
must never appear in core request objects, response metadata, exceptions, or logs.

## Core Types

All public value objects are frozen Pydantic models with forbidden extra fields.

### `LLMMessage`

- `role`: `SYSTEM`, `USER`, or `ASSISTANT`;
- `content`: non-empty text.

The role enum belongs in `core/llm/types.py` because it is specific to the LLM contract, not a
repository-wide domain enum.

### `LLMRequest`

- `messages`: a non-empty tuple of messages;
- `system_prompt`: optional non-empty text;
- `temperature`: optional finite value from `0.0` through `2.0`;
- `max_tokens`: positive integer, default `2048`, maximum `131072`;
- `metadata`: immutable caller context intended for local correlation only.

The request does not contain provider credentials, provider URLs, or an Ollama model name. Its
bounded default ensures every provider call carries an explicit generation ceiling. Provider
configuration belongs to each adapter. `system_prompt` is a first-class field and is translated to
the provider's native system message representation.

### `LLMUsage`

- `prompt_tokens`: optional non-negative integer;
- `completion_tokens`: optional non-negative integer;
- `total_tokens`: optional non-negative integer.

Usage is optional because not every provider reports token counts. Adapters must not fabricate
counts.

### `LLMModelMetadata`

- `provider`: stable provider identifier;
- `model`: provider model identifier;
- `details`: sanitized provider-specific metadata.

Metadata must never contain credentials or request headers.

### `LLMResponse`

- `content`: generated text;
- `finish_reason`: optional normalized/provider reason;
- `usage`: optional `LLMUsage`;
- `model`: `LLMModelMetadata`.

## Provider Protocol

`LLMProvider` exposes one operation:

```python
async def generate(self, request: LLMRequest) -> LLMResponse: ...
```

The protocol is runtime-checkable and contains no lifecycle, routing, retry, or agent logic. Each
provider instance owns its immutable configuration. This keeps consumers independent of constructor
details such as a future gateway's `base_url` and API key.

## Normalized Errors

All adapter failures exposed to consumers derive from `LLMProviderError`:

- `LLMConfigurationError`: invalid or missing provider configuration;
- `LLMTimeoutError`: the configured deadline expired;
- `LLMConnectionError`: the provider could not be reached;
- `LLMResponseError`: HTTP failure or malformed/unsupported response.

Errors expose a safe message, provider identifier, and optional status code. They must not embed
credentials, request headers, full prompt bodies, or raw response bodies.

Cancellation remains cancellation: adapters must not convert `asyncio.CancelledError` into a
provider error.

## Ollama Adapter

`OllamaLLMProvider` uses `httpx.AsyncClient` and Ollama's public chat HTTP endpoint. It receives:

- `base_url`, defaulting to `http://localhost:11434`;
- `model`;
- a positive timeout in seconds;
- an optional injected `httpx.AsyncClient` for controlled tests and caller-owned connection pools.
- a positive maximum response size in bytes.

The adapter sends non-streaming chat requests. It prepends `system_prompt` as a system message and
then preserves the caller message order. Request options are included only when supplied.

The adapter reads the response incrementally and rejects it when the configured byte limit is
exceeded. It extracts generated content, model identity, completion reason, Ollama token counters
when present, and an allowlisted subset of model details. Unknown response fields are ignored.
Missing required response structure raises `LLMResponseError`.

Client ownership is explicit: an injected client is never closed by the provider. A provider-created
client is reused to avoid repeated connection and TLS setup, and is released through `aclose()` or
the adapter's asynchronous context manager. Calling `generate()` after closure fails explicitly.

## Configuration

Application settings add:

- `ollama_base_url`, environment key `OLLAMA_BASE_URL`;
- `ollama_model`, environment key `OLLAMA_MODEL`;
- `ollama_timeout_seconds`, environment key `OLLAMA_TIMEOUT_SECONDS`.
- `ollama_max_response_bytes`, environment key `OLLAMA_MAX_RESPONSE_BYTES`.

Defaults support local development but do not start or require Ollama. No API key is introduced for
Ollama. Future gateway credentials will use provider-specific secret settings and will not alter the
core contracts.

## Fake Provider

`FakeLLMProvider` is a deterministic implementation of the same protocol. It accepts queued
responses or an error, records immutable requests for assertions up to a configurable finite
history limit, and never performs I/O. Exhausted response queues and exhausted history capacity fail
explicitly instead of inventing output or growing memory without bound.

The fake is shipped in `infrastructure/llm/fake.py` so application-level tests can reuse it without
reimplementing mocks. It is not selected automatically in production.

## Test Strategy

Every behavior follows RED-GREEN-REFACTOR. Tests first prove:

- strict validation and immutability of core types;
- protocol substitutability;
- fake response order, request recording, exhaustion, and configured errors;
- exact Ollama message ordering and optional request options;
- response, token, finish-reason, and model-metadata translation;
- absent token counters remain absent;
- timeout, connection, HTTP, and malformed-response normalization;
- cancellation propagation;
- oversized response rejection without exposing its body;
- absence of implicit retries;
- injected clients are not closed;
- provider-owned clients are reused and explicitly closed;
- environment configuration is parsed and validated.

Ollama HTTP tests use `httpx.MockTransport`; no test connects to a real Ollama service. The complete
repository test suite continues to use real PostgreSQL where persistence is involved. Final gates
are pytest, Ruff lint, Ruff format check, strict mypy, Docker/Alembic validation, health check, and
an independent code review.

## Documentation and Acceptance

Phase 4 adds an ADR and an LLM-provider usage document, and updates `.env.example`, README,
`AGENTS.md`, and the ADR index. Only Phase 4 checklist items that pass their validation are checked.
No Phase 5 checkbox or functionality is changed.
