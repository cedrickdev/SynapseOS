# Agent Core

Phase 5 provides a small, provider-neutral runtime for one agent. It exposes four bounded
asynchronous operations: `observe()`, `plan()`, `decide()`, and `report()`. It is a core-domain
consumer of `LLMProvider`, not an orchestrator or an execution environment.

## Construct and call an agent

The caller creates an immutable `AgentProfile`, constructs or receives an `LLMProvider`, and
injects that provider into `Agent`. `FakeLLMProvider` is suitable for deterministic tests and
controlled development; a composition root may inject a real Phase 4 provider instead.

```python
import asyncio
from decimal import Decimal

from core.agents import Agent, AgentProfile
from core.enums import AgentSeniority, AgentStatus
from core.llm import LLMModelMetadata, LLMResponse
from infrastructure.llm import FakeLLMProvider


async def main() -> None:
    profile = AgentProfile(
        id="backend-agent-01",
        name="Backend Agent 01",
        role="Backend Engineer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
        system_prompt="Observe the supplied subject and surface uncertainty.",
        autonomy_level=2,
        permission_ids={"repository.read"},
        tool_ids={"repository-search"},
        skill_ids={"generic-backend"},
        reputation_score=Decimal("0.90"),
        reliability_score=Decimal("0.95"),
    )
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=(
                    '{"summary":"The subject is bounded.","facts":[],"uncertainties":[],"risks":[]}'
                ),
                model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
            )
        ]
    )
    agent = Agent(profile, provider, max_history=100, max_tokens=512)

    observation = await agent.observe("Inspect the API boundary.")
    print(observation.summary)


asyncio.run(main())
```

The agent does not own the injected provider or its clients. The composition root that creates a
real provider is responsible for configuring and closing it according to that provider's lifecycle
contract. For example, provider-owned HTTP clients remain owned by the Phase 4 adapter, not by
`Agent`.

## Operations and results

Each operation accepts bounded, validated inputs and returns a frozen Pydantic value with forbidden
extra fields:

- `observe(subject) -> Observation` interprets one supplied subject.
- `plan(observation, objective) -> Plan` produces an ordered plan and success criteria.
- `decide(observation, plan) -> Decision` produces a choice, bounded evidence, confidence, and a
  human-approval signal.
- `report(observation, plan, decision) -> AgentReport` produces a terminal outcome, details, and
  suggested next actions.

Every operation constructs one provider-neutral `LLMRequest`, asks for exactly one JSON object, and
makes exactly one `LLMProvider.generate()` call. There is no retry, repair request, fallback, or
duplicate call. The caller controls what to do after the returned value; `next_actions` are data,
not commands that the runtime executes.

## Structured validation and failures

The runtime accepts only a single JSON object that strictly matches the expected result model.
Prose, Markdown fences, duplicate keys, unknown fields, non-finite numbers, incorrect field types,
blank required text, and values outside explicit size or cardinality limits are rejected.

Malformed model output raises `AgentOutputValidationError`. Its stable message identifies only the
expected result type and excludes prompts, raw responses, validation input, provider details,
credentials, and other sensitive content. Provider exceptions and `asyncio.CancelledError` pass
through unchanged. Failed or cancelled calls do not create history entries.

## Bounded history and ownership

On successful validation only, the agent retains one in-memory `AgentHistoryEntry`. History is a
fixed-size deque (default capacity: 100); once full, it evicts the oldest entry. The public
`history` property returns an immutable tuple snapshot.

Each entry contains only the operation name, a UTC completion time, normalized provider and model
labels, and optional token-usage counters. The runtime never persists history and never retains
subjects, objectives, system prompts, request messages, structured values, raw model responses,
provider metadata details, or errors. It is not persistent memory and it is not the audit log.

`AgentProfile` is also immutable. Its identity, role, department, seniority, status, autonomy,
permission identifiers, tool identifiers, skill identifiers, reputation score, and reliability
score cannot be modified by an operation.

## Deliberate Phase 5 boundary

`tool_ids` and `skill_ids` are declarations only. They neither grant a permission nor resolve or
execute a capability. The runtime does not execute tools, load skills, own provider clients, retry,
persist prompts or responses, or run autonomously.

In particular, `skill_ids` are inert until the Phase 8 Skills Registry. Phase 5 does not discover,
read, parse, select, or execute any `SKILL.md`, whether project-local or external. Future skill
loading must add explicit provenance, trust, permission, and sandbox controls in its designated
phase.

Phase 5 also contains no shell, terminal, filesystem, Git, database, MCP, network-tool, tool
registry, permission engine, autonomous loop, orchestration, or multi-agent behavior. Those
capabilities require later, separately reviewed phases.
