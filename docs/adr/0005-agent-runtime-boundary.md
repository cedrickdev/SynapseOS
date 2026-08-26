# ADR-0005 — Agent runtime boundary

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** SynapseOS maintainers

## Context

Phase 5 needs a useful runtime representation of one agent without conflating transient LLM work
with the persisted organisational `Agent` model. The boundary must support deterministic tests,
remain provider-neutral, avoid retaining sensitive prompts and model responses, and leave execution
authority to later phases.

## Options considered

- Bind runtime behavior to the SQLAlchemy `Agent` model — convenient for persistence access, but
  couples core behavior to infrastructure and blurs runtime ownership, loading, and audit concerns.
- Introduce an actor or autonomous loop — enables ongoing work, but prematurely creates
  orchestration, retry, state, permission, cancellation, and multi-agent responsibilities.
- Keep a separate immutable runtime profile with one-call structured operations — provides a small,
  testable core boundary while preserving later design choices.

## Decision

Keep `core.agents.Agent` and `AgentProfile` separate from SQLAlchemy persistence models. The runtime
receives an immutable profile and an injected provider-neutral `LLMProvider`; it owns neither the
provider client nor its lifecycle.

Expose only `observe()`, `plan()`, `decide()`, and `report()`. Each operation validates its inputs,
builds one bounded request, rejects any generated user prompt over 262,144 characters before the
provider is called, performs exactly one provider call with no retry or fallback, strictly decodes
one JSON object, and returns an immutable structured result. Invalid output produces a safe
`AgentOutputValidationError`; provider errors and cancellation propagate without transformation.

Retain only a bounded in-memory history of successful-operation metadata: operation, UTC timestamp,
provider label, model label, and optional token usage. Do not persist prompts, requests, responses,
structured outputs, provider metadata details, errors, or runtime history. `tool_ids` and
`skill_ids` remain inert declarations; `SKILL.md` loading waits for the Phase 8 Skills Registry.

## Consequences

- Core runtime behavior stays independent of SQLAlchemy, FastAPI, HTTP clients, and provider-specific
  adapters.
- Composition roots choose and close real providers; `FakeLLMProvider` keeps runtime tests
  deterministic and network-free.
- The agent cannot execute tools, access shell/files/MCP, modify its profile, grant permissions, or
  continue work without a caller.
- Persistence mapping, durable memory, auditing, tool execution, permission evaluation, retries,
  orchestration, actor loops, and multi-agent coordination remain deferred to their designated
  phases.
