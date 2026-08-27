# Phase 5 Agent Core Design

## Status

Approved on 2026-08-26.

## Goal

Introduce the first provider-neutral runtime representation of a SynapseOS agent. The runtime
agent encapsulates a validated profile and exposes four bounded, structured LLM operations:
`observe()`, `plan()`, `decide()`, and `report()`.

## Scope

Phase 5 includes:

- an immutable runtime agent profile containing identity, role, department, seniority, status,
  system prompt, autonomy, permissions, allowed tool identifiers, available skill identifiers,
  reputation, and reliability;
- immutable structured values for observations, plans, decisions, and reports;
- an asynchronous `Agent` runtime that depends only on the provider-neutral `LLMProvider`;
- strict JSON decoding and Pydantic validation for every LLM-produced value;
- bounded prompt inputs, structured collections, generated tokens, and runtime history;
- deterministic tests using the existing `FakeLLMProvider`;
- documentation and an ADR for the runtime boundary.

Phase 5 excludes:

- autonomous loops, retries, replanning loops, orchestration, or multi-agent coordination;
- shell, terminal, filesystem, network-tool, Git, database, or MCP execution;
- tool registration or invocation;
- loading, parsing, selecting, or executing `SKILL.md` files;
- permission evaluation or self-granting permissions;
- persistent memory, prompt storage, response storage, or agent-profile repositories;
- reputation calculation, score aggregation, promotion, demotion, or learning loops;
- provider routing, fallback, or cloud-provider implementation.

## Architectural Boundary

The runtime remains a core-domain consumer of the Phase 4 LLM contract:

```text
Caller -> core.agents.Agent -> core.llm.LLMProvider -> provider adapter
                         |
                         +-> validated structured value
```

`core/agents` may import `core/enums` and `core/llm`. It must not import SQLAlchemy,
`infrastructure`, FastAPI, HTTP clients, or provider-specific types. The runtime `Agent` and the
SQLAlchemy `infrastructure.database.models.organization.Agent` intentionally remain separate:
one performs bounded runtime behavior, while the other represents persisted organizational data.
No mapping layer is introduced in this phase.

## Runtime Profile

`AgentProfile` is a frozen Pydantic model with forbidden extra fields. It contains:

- `id`: stable non-blank agent identifier;
- `name`: non-blank display name;
- `role`: non-blank craft-oriented role;
- `department`: non-blank department identifier;
- `seniority`: shared `AgentSeniority` enum;
- `status`: shared `AgentStatus` enum;
- `system_prompt`: non-blank text with a maximum of 16,384 characters;
- `autonomy_level`: integer from `0` through `5`;
- `permission_ids`: immutable set of validated identifiers;
- `tool_ids`: immutable set of validated identifiers;
- `skill_ids`: immutable set of validated identifiers;
- `reputation_score`: finite decimal from `0.0` through `1.0`;
- `reliability_score`: finite decimal from `0.0` through `1.0`.

Identifiers use lowercase ASCII letters, digits, dots, underscores, hyphens, and colons, are at
most 128 characters, and cannot be blank. Each identifier set contains at most 128 items. These
sets are declarations only: possession of an identifier does not load a capability, grant a
permission, or authorize execution.

The profile is supplied directly to the runtime. Loading or persisting profiles is outside Phase 5.

## Future `SKILL.md` Compatibility

`AgentProfile.skill_ids` deliberately prepares the runtime for the Phase 8 Skills Registry. A
future registry will resolve identifiers to project-local, versioned skill packages shaped as:

```text
skills/<skill-id>/SKILL.md
skills/<skill-id>/metadata.yaml
```

Phase 5 never reads `~/.claude/skills`, `~/.codex/skills`, or any other external catalog. Future
imports must be explicit and must preserve provenance, version, checksum, trust level, required
permissions, and path containment. Skill instructions are untrusted data; they cannot grant
permissions or cause scripts and tools to execute without the later permission, tool, and sandbox
layers.

## Structured Values

All values are frozen Pydantic models with forbidden extra fields. Text fields reject blank values
and have explicit maximum lengths. Collection fields use tuples and have explicit item limits.

### `Observation`

- `summary`: concise interpretation of the supplied subject, maximum 4,096 characters;
- `facts`: up to 32 factual statements, each at most 1,024 characters;
- `uncertainties`: up to 16 explicit uncertainties, each at most 1,024 characters;
- `risks`: up to 16 identified risks, each at most 1,024 characters.

### `Plan`

- `objective`: the bounded objective, maximum 2,048 characters;
- `steps`: between 1 and 32 ordered steps, each at most 2,048 characters;
- `success_criteria`: between 1 and 16 verifiable criteria, each at most 1,024 characters;
- `risks`: up to 16 plan-specific risks, each at most 1,024 characters;

### `Decision`

- `choice`: selected action or conclusion, maximum 4,096 characters;
- `rationale`: evidence-oriented explanation, maximum 8,192 characters;
- `confidence`: finite value from `0.0` through `1.0` describing this decision only;
- `requires_human_approval`: boolean escalation signal;
- `evidence`: up to 32 concise evidence items, each at most 1,024 characters.

Decision confidence is not agent reputation and does not create an `AgentScore` in this phase.

### `AgentReport`

- `summary`: result summary, maximum 4,096 characters;
- `outcome`: `SUCCEEDED`, `FAILED`, `BLOCKED`, or `NEEDS_HUMAN`;
- `details`: up to 32 bounded report details, each at most 2,048 characters;
- `next_actions`: up to 16 bounded next actions, each at most 1,024 characters.

The report outcome enum belongs in `core/agents/types.py` because it is runtime-specific and is not
persisted or shared by the current data model.

## Agent Operations

The runtime constructor receives an `AgentProfile`, an injected `LLMProvider`, a positive
`max_history`, and a positive per-call `max_tokens` not exceeding the Phase 4 limit. Defaults are
`max_history=100` and `max_tokens=2048`.

The public asynchronous methods are:

```python
async def observe(self, subject: str) -> Observation: ...
async def plan(self, observation: Observation, objective: str) -> Plan: ...
async def decide(self, observation: Observation, plan: Plan) -> Decision: ...
async def report(
    self,
    observation: Observation,
    plan: Plan,
    decision: Decision,
) -> AgentReport: ...
```

`subject` and `objective` reject blank text and are limited to 32,768 and 8,192 characters,
respectively. Each method:

1. validates all caller input before contacting the provider;
2. constructs one `LLMRequest` with the profile system prompt and one bounded user message;
3. requests JSON only and includes the target schema contract in the bounded instruction;
4. performs exactly one `provider.generate()` call;
5. parses the response with `json.loads()` and validates the target Pydantic model;
6. records one minimal history event after successful validation;
7. returns the validated immutable value.

There is no hidden retry, repair call, fallback, or duplicate provider request. A malformed output
fails explicitly instead of asking the model to fix itself.

The operation prompts contain only the data required by that operation. `plan()` receives the
validated observation, `decide()` receives the observation and plan, and `report()` receives the
observation, plan, and decision. Earlier raw prompts and raw provider responses are never replayed.

## Structured Output Decoder

`core/agents/structured_output.py` owns generic JSON decoding and Pydantic validation. It accepts a
response content string and the expected model type. Failures raise `AgentOutputValidationError`
with a stable safe message and expected output type. The exception never contains the raw response,
prompt, validation input, provider metadata, or credentials.

JSON must contain exactly one object accepted by the target model. Markdown fences, prose around
JSON, arrays at the root, unknown fields, non-finite numbers, and oversized fields are rejected.

Provider errors propagate unchanged. `asyncio.CancelledError` also propagates unchanged and no
history event is recorded for a cancelled operation.

## Minimal Bounded History

The runtime keeps an in-memory `deque` with a fixed maximum length. Each immutable
`AgentHistoryEntry` contains only:

- operation type: `OBSERVE`, `PLAN`, `DECIDE`, or `REPORT`;
- UTC completion timestamp;
- provider identifier;
- model identifier;
- optional non-negative token usage counters.

History never stores subjects, objectives, system prompts, request messages, structured outputs,
raw responses, provider metadata details, or errors. The public `history` property returns an
immutable tuple snapshot. Once capacity is reached, the oldest event is evicted. This is bounded
runtime observability, not persistent agent memory or the immutable audit log.

## Security and Resource Invariants

- All runtime inputs and outputs are bounded before retention.
- Every generation request carries explicit `max_tokens`.
- Each operation makes exactly one provider call and performs no implicit retry.
- Cancellation is not caught or transformed.
- Prompts and responses are never automatically persisted or placed in history.
- Safe exceptions never include prompts, responses, credentials, or provider metadata.
- The agent cannot modify its profile, identifiers, autonomy, permissions, tools, or skills.
- Skill and tool identifiers have no executable behavior in this phase.
- The runtime owns no network client and therefore closes no provider resources.
- Provider lifecycle remains the responsibility of the composition root that injected it.

## File Structure

Phase 5 creates focused modules:

- `core/agents/types.py`: profile, structured values, runtime enums, and history entry;
- `core/agents/errors.py`: safe agent-layer exceptions;
- `core/agents/structured_output.py`: strict JSON-to-Pydantic decoding;
- `core/agents/agent.py`: the runtime and four LLM operations;
- `tests/agents/`: unit tests for types, decoding, runtime behavior, limits, history, and safety;
- `docs/agent-core.md`: usage and operational constraints;
- `docs/adr/0005-agent-runtime-boundary.md`: durable architecture decision.

No migration, repository, API endpoint, CLI, worker, or provider adapter is added.

## Test Strategy

Every behavior follows RED-GREEN-REFACTOR. Tests prove:

- profile strictness, immutability, identifier syntax, set cardinality, autonomy bounds, score
  bounds, and text limits;
- structured value strictness, immutability, cardinality, text limits, finite confidence, and report
  outcomes;
- valid JSON decoding and rejection of prose, fences, arrays, unknown fields, non-finite values,
  and invalid field values;
- deterministic `observe()`, `plan()`, `decide()`, and `report()` outputs through
  `FakeLLMProvider`;
- exactly one request per operation, explicit token limits, system-prompt separation, and bounded
  operation inputs;
- provider errors and cancellation propagate without an additional call;
- malformed output raises a safe error that excludes the raw response;
- history records only successful operation metadata, returns immutable snapshots, and evicts the
  oldest entry at capacity;
- history excludes all prompt, subject, objective, response, and structured-output content;
- the runtime exposes no shell, filesystem, terminal, MCP, tool-execution, or multi-agent behavior.

The full repository suite continues to use real PostgreSQL for persistence tests. Final gates are
pytest, Ruff lint, Ruff format check, strict mypy, Docker/Alembic validation, health check, secret
scan, and independent security and code reviews.

## Documentation and Acceptance

Phase 5 updates README, `AGENTS.md`, the ADR index, and only the Phase 5 checklist items whose tests
and implementation are complete. Phase 6 and later checkboxes remain untouched. The implementation
does not merge Phase 4 or any earlier stacked branch and does not begin the Tool Registry.
