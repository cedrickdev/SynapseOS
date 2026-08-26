"""Security regression tests for agent exception boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from contextlib import suppress
from decimal import Decimal
from types import FrameType, ModuleType, TracebackType
from typing import Any

import pytest

from core.agents import Agent, AgentProfile, Decision, Observation, Plan
from core.enums import AgentSeniority, AgentStatus
from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse
from infrastructure.llm.fake import FakeLLMProvider

_PROMPT_LIMIT = 262_144

PROFILE_TRACEBACK_MARKER = "profile-traceback-marker-2d89"
OBSERVE_SUBJECT_TRACEBACK_MARKER = "observe-subject-traceback-marker-4e15"
OBSERVE_RESPONSE_TRACEBACK_MARKER = "observe-response-traceback-marker-77ab"
PLAN_OBSERVATION_TRACEBACK_MARKER = "plan-observation-traceback-marker-1af8"
PLAN_OBJECTIVE_TRACEBACK_MARKER = "plan-objective-traceback-marker-95c2"
PLAN_RESPONSE_TRACEBACK_MARKER = "plan-response-traceback-marker-c6d4"
DECIDE_OBSERVATION_TRACEBACK_MARKER = "decide-observation-traceback-marker-39dd"
DECIDE_PLAN_TRACEBACK_MARKER = "decide-plan-traceback-marker-b8e7"
DECIDE_RESPONSE_TRACEBACK_MARKER = "decide-response-traceback-marker-0f43"
REPORT_OBSERVATION_TRACEBACK_MARKER = "report-observation-traceback-marker-c61e"
REPORT_PLAN_TRACEBACK_MARKER = "report-plan-traceback-marker-3c08"
REPORT_DECISION_TRACEBACK_MARKER = "report-decision-traceback-marker-6ebf"
REPORT_RESPONSE_TRACEBACK_MARKER = "report-response-traceback-marker-28a5"
PROVIDER_INPUT_TRACEBACK_MARKER = "provider-input-traceback-marker-9299"
CANCELLED_INPUT_TRACEBACK_MARKER = "cancelled-input-traceback-marker-91f2"
FORGED_PROFILE_SYSTEM_PROMPT_MARKER = "forged-profile-system-prompt-marker-554d"
FORGED_PROFILE_PERMISSION_MARKER = "FORGED-PROFILE-PERMISSION-MARKER-82D1"
PROMPT_CAP_OBSERVATION_MARKER = "prompt-cap-observation-marker-e509"
PROMPT_CAP_PLAN_MARKER = "prompt-cap-plan-marker-53ae"


class CancellingProvider:
    """Provider double that raises one specific cancellation instance."""

    def __init__(self, error: asyncio.CancelledError) -> None:
        self.calls = 0
        self._error = error

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Cancel after accepting exactly one request argument."""
        del request
        self.calls += 1
        raise self._error


def _profile(system_prompt: str = PROFILE_TRACEBACK_MARKER) -> AgentProfile:
    """Return one complete profile with a marker-bearing system prompt."""
    return AgentProfile(
        id="backend-agent-03",
        name="Backend Agent 03",
        role="Backend Engineer",
        department="engineering",
        seniority=AgentSeniority.SENIOR,
        status=AgentStatus.AVAILABLE,
        system_prompt=system_prompt,
        autonomy_level=2,
        permission_ids={"git.read", "tests.execute"},
        tool_ids={"repository-search"},
        skill_ids={"generic-backend", "testing"},
        reputation_score=Decimal("0.91"),
        reliability_score=Decimal("0.93"),
    )


def _observation(marker: str = "safe-observation-marker") -> Observation:
    """Return one valid observation carrying a unique marker."""
    return Observation(
        summary=marker,
        facts=["Each operation receives immutable values."],
        uncertainties=["Provider responses are not retained."],
        risks=["Only one provider call is permitted."],
    )


def _plan(marker: str = "safe-plan-marker") -> Plan:
    """Return one valid plan carrying a unique marker."""
    return Plan(
        objective=marker,
        steps=["Use exactly one provider call."],
        success_criteria=["Return one validated value."],
        risks=["Do not retry a provider failure."],
    )


def _decision(marker: str = "safe-decision-marker") -> Decision:
    """Return one valid decision carrying a unique marker."""
    return Decision(
        choice=marker,
        rationale="The runtime must preserve the provider boundary.",
        confidence=0.5,
        requires_human_approval=True,
        evidence=["The task specifies one provider call."],
    )


def _invalid_response(marker: str) -> LLMResponse:
    """Return a raw provider response that cannot decode as structured JSON."""
    return LLMResponse(
        content=marker,
        model=LLMModelMetadata(provider="fake", model="deterministic-invalid-v1"),
    )


def _decision_response() -> LLMResponse:
    """Return one valid decision response for prompt-cap tests."""
    return LLMResponse(
        content=(
            '{"choice":"Reject excessive prompt.","rationale":"The prompt cap is explicit.",'
            '"confidence":0.75,"requires_human_approval":false,"evidence":[]}'
        ),
        model=LLMModelMetadata(provider="fake", model="deterministic-decision-v1"),
    )


def _plan_response() -> LLMResponse:
    """Return one valid plan response for prompt-cap tests."""
    return LLMResponse(
        content=(
            '{"objective":"Accept bounded prompt.","steps":["Call the provider once."],'
            '"success_criteria":["The request stays below the cap."],"risks":[]}'
        ),
        model=LLMModelMetadata(provider="fake", model="deterministic-plan-v1"),
    )


def _escape_heavy_observation(marker: str = PROMPT_CAP_OBSERVATION_MARKER) -> Observation:
    """Return the largest valid observation when serialized JSON escapes every character."""
    return Observation(
        summary=marker + "\\" * (4_096 - len(marker)),
        facts=["\\" * 1_024] * 32,
        uncertainties=["\\" * 1_024] * 16,
        risks=["\\" * 1_024] * 16,
    )


def _escape_heavy_plan(marker: str = PROMPT_CAP_PLAN_MARKER) -> Plan:
    """Return the largest valid plan when serialized JSON escapes every character."""
    return Plan(
        objective=marker + "\\" * (2_048 - len(marker)),
        steps=["\\" * 2_048] * 32,
        success_criteria=["\\" * 1_024] * 16,
        risks=["\\" * 1_024] * 16,
    )


def _assert_text_excludes_markers(text: str, markers: Iterable[str], path: str) -> None:
    for marker in markers:
        assert marker not in text, f"{marker} remains reachable at {path}"


def _assert_object_excludes_markers(
    value: Any,
    markers: tuple[str, ...],
    *,
    path: str,
    seen: set[int],
    depth: int = 0,
) -> None:
    """Recursively inspect reachable local values without echoing secret values on failure."""
    if depth > 8:
        return
    if isinstance(value, str):
        _assert_text_excludes_markers(value, markers, path)
        return
    if isinstance(value, bytes):
        return
    value_id = id(value)
    if value_id in seen:
        return
    seen.add(value_id)
    with suppress(Exception):
        _assert_text_excludes_markers(repr(value), markers, f"{path}.repr")
    if value is None or isinstance(value, bool | int | float | Decimal | ModuleType | FrameType):
        return
    if isinstance(value, BaseException):
        _assert_object_excludes_markers(
            value.args,
            markers,
            path=f"{path}.args",
            seen=seen,
            depth=depth + 1,
        )
        _assert_object_excludes_markers(
            vars(value),
            markers,
            path=f"{path}.__dict__",
            seen=seen,
            depth=depth + 1,
        )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_object_excludes_markers(
                key,
                markers,
                path=f"{path}.key",
                seen=seen,
                depth=depth + 1,
            )
            _assert_object_excludes_markers(
                item,
                markers,
                path=f"{path}[{key!r}]",
                seen=seen,
                depth=depth + 1,
            )
        return
    if isinstance(value, tuple | list | set | frozenset):
        for index, item in enumerate(value):
            _assert_object_excludes_markers(
                item,
                markers,
                path=f"{path}[{index}]",
                seen=seen,
                depth=depth + 1,
            )
        return
    if hasattr(value, "__dict__"):
        _assert_object_excludes_markers(
            vars(value),
            markers,
            path=f"{path}.__dict__",
            seen=seen,
            depth=depth + 1,
        )


def _assert_traceback_excludes_markers(
    traceback: TracebackType | None,
    markers: tuple[str, ...],
) -> None:
    """Inspect every traceback frame local and every repr reachable from each local."""
    while traceback is not None:
        frame = traceback.tb_frame
        for name, value in frame.f_locals.items():
            _assert_object_excludes_markers(
                value,
                markers,
                path=f"{frame.f_code.co_filename}:{frame.f_lineno}:{name}",
                seen=set(),
            )
        traceback = traceback.tb_next


def _assert_exception_excludes_markers(error: BaseException, markers: tuple[str, ...]) -> None:
    """Assert sensitive values are absent from public exception state and traceback locals."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None:
        _assert_text_excludes_markers(str(current), markers, "exception.str")
        _assert_text_excludes_markers(repr(current), markers, "exception.repr")
        _assert_object_excludes_markers(
            current.args,
            markers,
            path="exception.args",
            seen=seen,
        )
        _assert_object_excludes_markers(
            vars(current),
            markers,
            path="exception.__dict__",
            seen=seen,
        )
        _assert_traceback_excludes_markers(current.__traceback__, markers)
        current = current.__cause__ or current.__context__


def _capture_observe_decode_failure() -> tuple[BaseException, int, tuple[object, ...]]:
    profile = _profile()
    provider = FakeLLMProvider(responses=[_invalid_response(OBSERVE_RESPONSE_TRACEBACK_MARKER)])
    agent = Agent(profile, provider)
    captured: BaseException | None = None
    try:
        asyncio.run(agent.observe(OBSERVE_SUBJECT_TRACEBACK_MARKER))
    except BaseException as error:
        captured = error
        requests_count = len(provider.requests)
        history = agent.history
        del profile, provider, agent
        return captured, requests_count, history
    raise AssertionError("observe should have rejected malformed output")


def _capture_plan_decode_failure() -> tuple[BaseException, int, tuple[object, ...]]:
    profile = _profile()
    provider = FakeLLMProvider(responses=[_invalid_response(PLAN_RESPONSE_TRACEBACK_MARKER)])
    agent = Agent(profile, provider)
    observation = _observation(PLAN_OBSERVATION_TRACEBACK_MARKER)
    captured: BaseException | None = None
    try:
        asyncio.run(agent.plan(observation, PLAN_OBJECTIVE_TRACEBACK_MARKER))
    except BaseException as error:
        captured = error
        requests_count = len(provider.requests)
        history = agent.history
        del profile, provider, agent, observation
        return captured, requests_count, history
    raise AssertionError("plan should have rejected malformed output")


def _capture_decide_decode_failure() -> tuple[BaseException, int, tuple[object, ...]]:
    profile = _profile()
    provider = FakeLLMProvider(responses=[_invalid_response(DECIDE_RESPONSE_TRACEBACK_MARKER)])
    agent = Agent(profile, provider)
    observation = _observation(DECIDE_OBSERVATION_TRACEBACK_MARKER)
    plan = _plan(DECIDE_PLAN_TRACEBACK_MARKER)
    captured: BaseException | None = None
    try:
        asyncio.run(agent.decide(observation, plan))
    except BaseException as error:
        captured = error
        requests_count = len(provider.requests)
        history = agent.history
        del profile, provider, agent, observation, plan
        return captured, requests_count, history
    raise AssertionError("decide should have rejected malformed output")


def _capture_report_decode_failure() -> tuple[BaseException, int, tuple[object, ...]]:
    profile = _profile()
    provider = FakeLLMProvider(responses=[_invalid_response(REPORT_RESPONSE_TRACEBACK_MARKER)])
    agent = Agent(profile, provider)
    observation = _observation(REPORT_OBSERVATION_TRACEBACK_MARKER)
    plan = _plan(REPORT_PLAN_TRACEBACK_MARKER)
    decision = _decision(REPORT_DECISION_TRACEBACK_MARKER)
    captured: BaseException | None = None
    try:
        asyncio.run(agent.report(observation, plan, decision))
    except BaseException as error:
        captured = error
        requests_count = len(provider.requests)
        history = agent.history
        del profile, provider, agent, observation, plan, decision
        return captured, requests_count, history
    raise AssertionError("report should have rejected malformed output")


@pytest.mark.parametrize(
    ("capture", "markers"),
    [
        (
            _capture_observe_decode_failure,
            (
                PROFILE_TRACEBACK_MARKER,
                OBSERVE_SUBJECT_TRACEBACK_MARKER,
                OBSERVE_RESPONSE_TRACEBACK_MARKER,
            ),
        ),
        (
            _capture_plan_decode_failure,
            (
                PROFILE_TRACEBACK_MARKER,
                PLAN_OBSERVATION_TRACEBACK_MARKER,
                PLAN_OBJECTIVE_TRACEBACK_MARKER,
                PLAN_RESPONSE_TRACEBACK_MARKER,
            ),
        ),
        (
            _capture_decide_decode_failure,
            (
                PROFILE_TRACEBACK_MARKER,
                DECIDE_OBSERVATION_TRACEBACK_MARKER,
                DECIDE_PLAN_TRACEBACK_MARKER,
                DECIDE_RESPONSE_TRACEBACK_MARKER,
            ),
        ),
        (
            _capture_report_decode_failure,
            (
                PROFILE_TRACEBACK_MARKER,
                REPORT_OBSERVATION_TRACEBACK_MARKER,
                REPORT_PLAN_TRACEBACK_MARKER,
                REPORT_DECISION_TRACEBACK_MARKER,
                REPORT_RESPONSE_TRACEBACK_MARKER,
            ),
        ),
    ],
)
def test_output_failure_tracebacks_exclude_agent_sensitive_values(
    capture: Any,
    markers: tuple[str, ...],
) -> None:
    """Output validation failures must not retain prompts, responses, inputs, or profile."""
    error, requests_count, history = capture()

    assert requests_count == 1
    assert history == ()
    _assert_exception_excludes_markers(error, markers)


def _capture_provider_failure() -> tuple[BaseException, bool, int, tuple[object, ...]]:
    profile = _profile()
    provider_error = LLMProviderError("safe provider failure", provider="fake")
    provider = FakeLLMProvider(error=provider_error)
    agent = Agent(profile, provider)
    captured: BaseException | None = None
    observation = _observation(PROVIDER_INPUT_TRACEBACK_MARKER)
    try:
        asyncio.run(agent.plan(observation, "provider objective"))
    except LLMProviderError as error:
        captured = error
        same_identity = captured is provider_error
        requests_count = len(provider.requests)
        history = agent.history
        del profile, provider_error, provider, agent, observation
        return captured, same_identity, requests_count, history
    raise AssertionError("provider failure should have propagated")


def test_provider_failure_traceback_excludes_agent_request_and_inputs() -> None:
    """Provider errors must keep identity without retaining the generated request."""
    error, same_identity, requests_count, history = _capture_provider_failure()

    assert same_identity is True
    assert requests_count == 1
    assert history == ()
    _assert_exception_excludes_markers(
        error,
        (PROFILE_TRACEBACK_MARKER, PROVIDER_INPUT_TRACEBACK_MARKER),
    )


def _capture_cancellation_failure() -> tuple[BaseException, bool, int, tuple[object, ...]]:
    profile = _profile()
    cancellation = asyncio.CancelledError("safe cancellation")
    provider = CancellingProvider(cancellation)
    agent = Agent(profile, provider)
    captured: BaseException | None = None
    observation = _observation(CANCELLED_INPUT_TRACEBACK_MARKER)
    try:
        asyncio.run(agent.plan(observation, "cancelled objective"))
    except asyncio.CancelledError as error:
        captured = error
        same_identity = captured is cancellation
        calls = provider.calls
        history = agent.history
        del profile, cancellation, provider, agent, observation
        return captured, same_identity, calls, history
    raise AssertionError("cancellation should have propagated")


def test_cancellation_traceback_excludes_agent_request_and_inputs() -> None:
    """Cancellation must keep identity without retaining the generated request."""
    error, same_identity, calls, history = _capture_cancellation_failure()

    assert same_identity is True
    assert calls == 1
    assert history == ()
    _assert_exception_excludes_markers(
        error,
        (PROFILE_TRACEBACK_MARKER, CANCELLED_INPUT_TRACEBACK_MARKER),
    )


def _capture_forged_profile_error(forged_profile: AgentProfile) -> tuple[BaseException, int]:
    provider = FakeLLMProvider(responses=[_plan_response()])
    captured: BaseException | None = None
    try:
        Agent(forged_profile, provider)
    except ValueError as error:
        captured = error
        requests_count = len(provider.requests)
        del forged_profile, provider
        return captured, requests_count
    raise AssertionError("forged profile should have failed validation")


@pytest.mark.parametrize(
    ("forged_profile", "marker"),
    [
        (
            _profile().model_copy(
                update={
                    "system_prompt": FORGED_PROFILE_SYSTEM_PROMPT_MARKER
                    + "x" * (16_385 - len(FORGED_PROFILE_SYSTEM_PROMPT_MARKER))
                }
            ),
            FORGED_PROFILE_SYSTEM_PROMPT_MARKER,
        ),
        (
            _profile().model_copy(
                update={"permission_ids": frozenset({FORGED_PROFILE_PERMISSION_MARKER})}
            ),
            FORGED_PROFILE_PERMISSION_MARKER,
        ),
    ],
)
def test_constructor_revalidates_forged_profiles_without_leaking_profile_data(
    forged_profile: AgentProfile,
    marker: str,
) -> None:
    """A forged AgentProfile instance must fail before any request can be made."""
    error, requests_count = _capture_forged_profile_error(forged_profile)

    assert str(error) == "agent profile is invalid"
    assert error.args == ("agent profile is invalid",)
    assert requests_count == 0
    _assert_exception_excludes_markers(error, (marker,))


def test_escape_heavy_prompt_below_explicit_cap_is_accepted_with_one_request(
    agent_profile: AgentProfile,
) -> None:
    """Worst-case valid JSON escaping below the cap must still allow one provider call."""
    provider = FakeLLMProvider(responses=[_plan_response()])
    agent = Agent(agent_profile, provider)

    asyncio.run(agent.plan(_escape_heavy_observation(), "bounded objective"))

    assert len(provider.requests) == 1
    assert len(provider.requests[0].messages[0].content) <= _PROMPT_LIMIT
    assert len(agent.history) == 1


def _capture_prompt_cap_failure() -> tuple[BaseException, int, tuple[object, ...], int]:
    profile = _profile()
    provider = FakeLLMProvider(responses=[_decision_response()])
    agent = Agent(profile, provider)
    observation = _escape_heavy_observation()
    plan = _escape_heavy_plan()
    serialized_values_lower_bound = (
        len(observation.model_dump_json())
        + len(plan.model_dump_json())
        + len("\nObservation:\n\nPlan:\n\nDecision:\n")
    )
    captured: BaseException | None = None
    try:
        asyncio.run(agent.decide(observation, plan))
    except ValueError as error:
        captured = error
        requests_count = len(provider.requests)
        history = agent.history
        del profile, provider, agent, observation, plan
        return captured, requests_count, history, serialized_values_lower_bound
    raise AssertionError("escape-heavy prompt should have exceeded the cap")


def test_escape_heavy_prompt_above_explicit_cap_fails_before_provider_call() -> None:
    """A generated prompt above 262,144 characters must fail safely before generation."""
    error, requests_count, history, serialized_values_lower_bound = _capture_prompt_cap_failure()

    assert serialized_values_lower_bound > _PROMPT_LIMIT
    assert str(error) == "agent user prompt exceeds 262144 characters"
    assert error.args == ("agent user prompt exceeds 262144 characters",)
    assert requests_count == 0
    assert history == ()
    _assert_exception_excludes_markers(
        error,
        (PROFILE_TRACEBACK_MARKER, PROMPT_CAP_OBSERVATION_MARKER, PROMPT_CAP_PLAN_MARKER),
    )
