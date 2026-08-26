"""Behavioral tests for bounded agent planning, decisions, and reports."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine

import pytest

from core.agents import (
    Agent,
    AgentOutputValidationError,
    AgentProfile,
    AgentReport,
    AgentReportOutcome,
    Decision,
    Observation,
    Plan,
)
from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from infrastructure.llm.fake import FakeLLMProvider

type WorkflowOperation = Callable[[Agent], Coroutine[None, None, object]]


class CancellingProvider:
    """Provider double that records one attempted call before cancellation."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Cancel without producing a response."""
        del request
        self.calls += 1
        raise asyncio.CancelledError


def _workflow_values() -> tuple[Observation, Plan, Decision]:
    """Build independent complete values for operation-boundary tests."""
    return (
        Observation(
            summary="The supplied result has fixed bounded inputs.",
            facts=["Each operation receives immutable values."],
            uncertainties=["Provider responses are not retained."],
            risks=["Only one provider call is permitted."],
        ),
        Plan(
            objective="Complete the bounded workflow operation.",
            steps=["Use the supplied immutable values."],
            success_criteria=["Return one validated value."],
            risks=["Do not retry a provider failure."],
        ),
        Decision(
            choice="Keep the operation bounded.",
            rationale="The workflow contract allows no autonomous execution.",
            confidence=0.5,
            requires_human_approval=True,
            evidence=["The task specifies one provider call."],
        ),
    )


async def _call_plan(agent: Agent) -> object:
    """Run planning with one complete valid input pair."""
    observation, _, _ = _workflow_values()
    return await agent.plan(observation, "Complete the bounded workflow operation.")


async def _call_decide(agent: Agent) -> object:
    """Run decision-making with complete valid values."""
    observation, plan, _ = _workflow_values()
    return await agent.decide(observation, plan)


async def _call_report(agent: Agent) -> object:
    """Run reporting with complete valid values."""
    observation, plan, decision = _workflow_values()
    return await agent.report(observation, plan, decision)


def test_plan_returns_validated_plan_with_one_call(agent_profile: AgentProfile) -> None:
    """Planning must use only the supplied observation and one provider response."""
    objective = "Produce a bounded implementation plan."
    raw_prompt_marker = "earlier-raw-prompt-marker-638e"
    raw_response_marker = "earlier-raw-response-marker-b86a"
    observation = Observation(
        summary="The supplied repository needs a focused change.",
        facts=["The provider boundary is already available."],
        uncertainties=["No prior provider output may be replayed."],
        risks=["Adding an execution loop exceeds the task scope."],
    )
    response = LLMResponse(
        content=(
            '{"objective":"Produce a bounded implementation plan.",'
            '"steps":["Add the operation through a failing test."],'
            '"success_criteria":["The operation makes one provider call."],'
            '"risks":["Do not retain raw provider content."]}'
        ),
        model=LLMModelMetadata(provider="fake", model="deterministic-plan-v1"),
    )
    provider = FakeLLMProvider(responses=[response])
    agent = Agent(agent_profile, provider, max_tokens=1234)

    plan = asyncio.run(agent.plan(observation, objective))

    assert plan == Plan(
        objective=objective,
        steps=["Add the operation through a failing test."],
        success_criteria=["The operation makes one provider call."],
        risks=["Do not retain raw provider content."],
    )
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.system_prompt == agent_profile.system_prompt
    assert request.max_tokens == 1234
    assert len(request.messages) == 1
    assert request.messages[0].role is LLMRole.USER
    assert request.messages[0].content.count(objective) == 1
    serialized_observation = request.messages[0].content.split("Observation:\n", maxsplit=1)[1]
    assert json.loads(serialized_observation) == observation.model_dump(mode="json")
    assert raw_prompt_marker not in request.messages[0].content
    assert raw_response_marker not in request.messages[0].content
    assert agent.history[0].operation.value == "PLAN"


def test_decide_returns_validated_decision_with_one_call(agent_profile: AgentProfile) -> None:
    """Decisions must be strictly decoded from only the supplied values."""
    observation = Observation(
        summary="The supplied change requires a constrained decision.",
        facts=["The public contract has fixed fields."],
        uncertainties=["No raw response may enter the prompt."],
        risks=["A provider retry would violate the operation boundary."],
    )
    plan = Plan(
        objective="Select the bounded implementation path.",
        steps=["Use exactly one provider call."],
        success_criteria=["A valid immutable decision is returned."],
        risks=["Do not add a fallback provider."],
    )
    response = LLMResponse(
        content=(
            '{"choice":"Use the minimal one-call implementation.",'
            '"rationale":"It preserves the provider and history safety invariants.",'
            '"confidence":0.73,"requires_human_approval":false,'
            '"evidence":["The supplied plan requires one provider call."]}'
        ),
        model=LLMModelMetadata(provider="fake", model="deterministic-decision-v1"),
    )
    provider = FakeLLMProvider(responses=[response])
    agent = Agent(agent_profile, provider, max_tokens=987)

    decision = asyncio.run(agent.decide(observation, plan))

    assert decision == Decision(
        choice="Use the minimal one-call implementation.",
        rationale="It preserves the provider and history safety invariants.",
        confidence=0.73,
        requires_human_approval=False,
        evidence=["The supplied plan requires one provider call."],
    )
    assert decision.confidence == 0.73
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.system_prompt == agent_profile.system_prompt
    assert request.max_tokens == 987
    assert len(request.messages) == 1
    assert request.messages[0].role is LLMRole.USER
    serialized_observation, serialized_plan_and_instruction = request.messages[0].content.split(
        "\nObservation:\n", maxsplit=1
    )[1].split("\nPlan:\n", maxsplit=1)
    serialized_plan = serialized_plan_and_instruction.split("\nDecision:\n", maxsplit=1)[0]
    assert json.loads(serialized_observation) == observation.model_dump(mode="json")
    assert json.loads(serialized_plan) == plan.model_dump(mode="json")
    assert agent.history[0].operation.value == "DECIDE"


@pytest.mark.parametrize("outcome", list(AgentReportOutcome))
def test_report_returns_validated_report_with_one_call(
    agent_profile: AgentProfile,
    outcome: AgentReportOutcome,
) -> None:
    """Reporting must use only supplied immutable values and one provider response."""
    observation = Observation(
        summary="The supplied result is ready for bounded reporting.",
        facts=["The operation receives immutable inputs."],
        uncertainties=["No raw history can be replayed."],
        risks=["A second provider call would be unsafe."],
    )
    plan = Plan(
        objective="Report the completed bounded operation.",
        steps=["Serialize only the supplied value objects."],
        success_criteria=["Return a validated report."],
        risks=["Do not execute any next action."],
    )
    decision = Decision(
        choice="Produce a structured report.",
        rationale="The caller needs a bounded account of the completed operation.",
        confidence=0.64,
        requires_human_approval=False,
        evidence=["The validated plan defines a report objective."],
    )
    response = LLMResponse(
        content=(
            '{"summary":"The bounded operation was reported.",'
            f'"outcome":"{outcome.value}",'
            '"details":["Only validated values reached the provider."],'
            '"next_actions":["Return control to the caller."]}'
        ),
        model=LLMModelMetadata(provider="fake", model="deterministic-report-v1"),
    )
    provider = FakeLLMProvider(responses=[response])
    agent = Agent(agent_profile, provider, max_tokens=765)

    report = asyncio.run(agent.report(observation, plan, decision))

    assert report == AgentReport(
        summary="The bounded operation was reported.",
        outcome=outcome,
        details=["Only validated values reached the provider."],
        next_actions=["Return control to the caller."],
    )
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.system_prompt == agent_profile.system_prompt
    assert request.max_tokens == 765
    assert len(request.messages) == 1
    assert request.messages[0].role is LLMRole.USER
    serialized_observation, serialized_plan_and_rest = request.messages[0].content.split(
        "\nObservation:\n", maxsplit=1
    )[1].split("\nPlan:\n", maxsplit=1)
    serialized_plan, serialized_decision_and_instruction = serialized_plan_and_rest.split(
        "\nDecision:\n", maxsplit=1
    )
    serialized_decision = serialized_decision_and_instruction.split("\nReport:\n", maxsplit=1)[0]
    assert json.loads(serialized_observation) == observation.model_dump(mode="json")
    assert json.loads(serialized_plan) == plan.model_dump(mode="json")
    assert json.loads(serialized_decision) == decision.model_dump(mode="json")
    assert agent.history[0].operation.value == "REPORT"


@pytest.mark.parametrize(
    ("operation", "expected_type"),
    [
        (_call_plan, "Plan"),
        (_call_decide, "Decision"),
        (_call_report, "AgentReport"),
    ],
)
def test_workflow_operations_reject_malformed_output_without_history(
    agent_profile: AgentProfile,
    operation: WorkflowOperation,
    expected_type: str,
) -> None:
    """Invalid provider output must not leak or produce a completed event."""
    marker = "malformed-workflow-output-marker-7a3d"
    response = LLMResponse(
        content=marker,
        model=LLMModelMetadata(provider="fake", model="deterministic-invalid-v1"),
    )
    provider = FakeLLMProvider(responses=[response])
    agent = Agent(agent_profile, provider)

    with pytest.raises(AgentOutputValidationError) as raised:
        asyncio.run(operation(agent))

    assert raised.value.expected_type == expected_type
    assert marker not in str(raised.value)
    assert marker not in repr(raised.value)
    assert len(provider.requests) == 1
    assert agent.history == ()


@pytest.mark.parametrize("operation", [_call_plan, _call_decide, _call_report])
def test_workflow_operations_propagate_provider_errors_without_retry(
    agent_profile: AgentProfile,
    operation: WorkflowOperation,
) -> None:
    """Provider errors must retain identity after exactly one attempted request."""
    error = LLMProviderError("workflow-provider-error-marker-47fb", provider="fake")
    provider = FakeLLMProvider(error=error)
    agent = Agent(agent_profile, provider)

    with pytest.raises(LLMProviderError) as raised:
        asyncio.run(operation(agent))

    assert raised.value is error
    assert len(provider.requests) == 1
    assert agent.history == ()


@pytest.mark.parametrize("operation", [_call_plan, _call_decide, _call_report])
def test_workflow_operations_propagate_cancellation_without_retry(
    agent_profile: AgentProfile,
    operation: WorkflowOperation,
) -> None:
    """Cancellation must pass through and never become successful history."""
    provider = CancellingProvider()
    agent = Agent(agent_profile, provider)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(operation(agent))

    assert provider.calls == 1
    assert agent.history == ()


@pytest.mark.parametrize("objective", [" \t\n", "x" * 8_193])
def test_plan_rejects_invalid_objective_before_calling_provider(
    agent_profile: AgentProfile,
    objective: str,
) -> None:
    """Objective validation must run before the provider receives a request."""
    observation, _, _ = _workflow_values()
    provider = FakeLLMProvider()
    agent = Agent(agent_profile, provider)

    with pytest.raises(ValueError):
        asyncio.run(agent.plan(observation, objective))

    assert provider.requests == ()
    assert agent.history == ()


def test_decide_rejects_invalid_confidence_without_history(agent_profile: AgentProfile) -> None:
    """A decision response with out-of-range confidence must fail strict validation."""
    observation, plan, _ = _workflow_values()
    response = LLMResponse(
        content=(
            '{"choice":"Keep the operation bounded.",'
            '"rationale":"The workflow contract allows no autonomous execution.",'
            '"confidence":1.01,"requires_human_approval":true,'
            '"evidence":["The task specifies one provider call."]}'
        ),
        model=LLMModelMetadata(provider="fake", model="deterministic-invalid-v1"),
    )
    provider = FakeLLMProvider(responses=[response])
    agent = Agent(agent_profile, provider)

    with pytest.raises(AgentOutputValidationError) as raised:
        asyncio.run(agent.decide(observation, plan))

    assert raised.value.expected_type == "Decision"
    assert len(provider.requests) == 1
    assert agent.history == ()


def _maximum_observation() -> Observation:
    """Build the largest valid observation using compact ASCII values."""
    return Observation(
        summary="o" * 4_096,
        facts=["f" * 1_024] * 32,
        uncertainties=["u" * 1_024] * 16,
        risks=["r" * 1_024] * 16,
    )


def _maximum_plan() -> Plan:
    """Build the largest valid plan using compact ASCII values."""
    return Plan(
        objective="p" * 2_048,
        steps=["s" * 2_048] * 32,
        success_criteria=["c" * 1_024] * 16,
        risks=["r" * 1_024] * 16,
    )


def _maximum_decision() -> Decision:
    """Build the largest valid decision using compact ASCII values."""
    return Decision(
        choice="c" * 4_096,
        rationale="r" * 8_192,
        confidence=1.0,
        requires_human_approval=True,
        evidence=["e" * 1_024] * 32,
    )


def test_workflow_prompt_sizes_are_bounded_by_value_contracts(
    agent_profile: AgentProfile,
) -> None:
    """Maximum valid values must still produce bounded operation prompts."""
    responses = [
        LLMResponse(
            content=(
                '{"objective":"Return a bounded plan.","steps":["Return one value."],'
                '"success_criteria":["The value is valid."],"risks":[]}'
            ),
            model=LLMModelMetadata(provider="fake", model="deterministic-plan-v1"),
        ),
        LLMResponse(
            content=(
                '{"choice":"Return a bounded decision.",'
                '"rationale":"The value has fixed limits.","confidence":1.0,'
                '"requires_human_approval":true,"evidence":[]}'
            ),
            model=LLMModelMetadata(provider="fake", model="deterministic-decision-v1"),
        ),
        LLMResponse(
            content=(
                '{"summary":"Return a bounded report.","outcome":"SUCCEEDED",'
                '"details":[],"next_actions":[]}'
            ),
            model=LLMModelMetadata(provider="fake", model="deterministic-report-v1"),
        ),
    ]
    provider = FakeLLMProvider(responses=responses)
    agent = Agent(agent_profile, provider)
    observation = _maximum_observation()
    plan = _maximum_plan()
    decision = _maximum_decision()

    asyncio.run(agent.plan(observation, "o" * 8_192))
    asyncio.run(agent.decide(observation, plan))
    asyncio.run(agent.report(observation, plan, decision))

    assert len(provider.requests) == 3
    assert len(provider.requests[0].messages[0].content) <= 80_000
    assert len(provider.requests[1].messages[0].content) <= 175_000
    assert len(provider.requests[2].messages[0].content) <= 220_000
