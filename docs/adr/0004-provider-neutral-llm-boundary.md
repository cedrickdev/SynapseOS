# ADR-0004 — Provider-neutral LLM boundary

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** SynapseOS maintainers

## Context

SynapseOS must begin with local Ollama models while remaining ready for MLX, API gateways, and cloud
providers. Provider behavior must be bounded, resource-conscious, testable without network access,
and unable to leak prompts or credentials through errors.

## Options considered

- Depend directly on the Ollama SDK — convenient, but couples consumers to one provider.
- Introduce a multi-provider framework — broad coverage, but premature routing complexity.
- Define core contracts and an independent HTTP adapter — a small stable boundary with explicit
  translation and lifecycle control.

## Decision

Core owns immutable provider-neutral values, normalized errors, and an asynchronous protocol.
Infrastructure owns a bounded Ollama adapter built on `httpx` and a deterministic fake. Ollama is
called through its public HTTP contract rather than a provider SDK.

Each provider call has a wall-clock timeout, response-size limit, and bounded token control;
performs no hidden retry
or persistence; preserves cancellation; filters metadata; and exposes only safe errors. Provider-
owned HTTP pools require explicit closure, while injected clients remain caller-owned.

Core metadata accepts only recursively immutable, finite JSON-compatible values. Ollama metadata is
further restricted to documented keys with bounded primitive value shapes.

## Consequences

- Consumers can change providers without changing their request or response code.
- Future gateway credentials remain isolated in provider-specific configuration.
- Routing, retries, fallback, budgets, tool calling, cloud providers, and MLX remain deferred.
- The adapter maintains provider translation code, but its behavior is fully unit-testable without
  a real Ollama service.
