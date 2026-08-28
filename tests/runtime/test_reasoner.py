"""Strict one-shot LLM reasoning tests for Phase 13."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from core.llm import LLMModelMetadata, LLMResponse, LLMUsage
from core.runtime import (
    LLMLoopReasoner,
    RuntimeAction,
    RuntimeError,
    RuntimeErrorCode,
    RuntimeObservation,
    RuntimePlan,
    RuntimeTask,
)
from infrastructure.llm import FakeLLMProvider


def _response(content: str, usage: LLMUsage | None = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="stop",
        usage=usage,
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )


def _task() -> RuntimeTask:
    return RuntimeTask(
        task_id=uuid4(),
        objective="Inspect the repository safely.",
        acceptance_criteria=("The repository was inspected.",),
    )


def _observation() -> RuntimeObservation:
    return RuntimeObservation(
        summary="The repository requires inspection.",
        facts=("README.md is declared as the target.",),
        uncertainties=(),
    )


def _plan() -> RuntimePlan:
    return RuntimePlan(
        objective="Inspect the repository safely.",
        steps=("Read README.md.",),
        success_criteria=("The file is observed.",),
    )


def test_decide_decodes_one_closed_tool_action_and_authoritative_usage() -> None:
    provider = FakeLLMProvider(
        responses=[
            _response(
                '{"action":"TOOL_CALL","tool_name":"fake_read",'
                '"arguments":{"path":"README.md"},'
                '"rationale":"Inspect the declared file.","confidence":0.9}',
                LLMUsage(prompt_tokens=30, completion_tokens=12, total_tokens=42),
            )
        ]
    )
    reasoner = LLMLoopReasoner(
        provider,
        system_prompt="Operate only through structured actions.",
        max_step_tokens=512,
    )

    output = asyncio.run(reasoner.decide(_task(), _observation(), _plan(), ()))

    assert output.value.action is RuntimeAction.TOOL_CALL
    assert output.value.tool_name == "fake_read"
    assert output.value.arguments == {"path": "README.md"}
    assert output.reported_tokens == 42
    assert output.usage_available is True
    assert len(provider.requests) == 1
    assert provider.requests[0].max_tokens == 512


def test_usage_falls_back_to_reported_prompt_and_completion_sum() -> None:
    provider = FakeLLMProvider(
        responses=[
            _response(
                '{"summary":"Repository observed.","facts":[],"uncertainties":[]}',
                LLMUsage(prompt_tokens=7, completion_tokens=5, total_tokens=None),
            )
        ]
    )
    reasoner = LLMLoopReasoner(provider, system_prompt="Observe safely.", max_step_tokens=128)

    output = asyncio.run(reasoner.observe(_task(), ()))

    assert output.reported_tokens == 12
    assert output.usage_available is True


def test_missing_usage_is_explicitly_unavailable_and_not_estimated() -> None:
    provider = FakeLLMProvider(
        responses=[_response('{"summary":"Repository observed.","facts":[],"uncertainties":[]}')]
    )
    reasoner = LLMLoopReasoner(provider, system_prompt="Observe safely.", max_step_tokens=128)

    output = asyncio.run(reasoner.observe(_task(), ()))

    assert output.reported_tokens == 0
    assert output.usage_available is False


def test_oversized_provider_usage_fails_closed_without_retry() -> None:
    provider = FakeLLMProvider(
        responses=[
            _response(
                '{"summary":"Repository observed.","facts":[],"uncertainties":[]}',
                LLMUsage(total_tokens=10_000_001),
            )
        ]
    )
    reasoner = LLMLoopReasoner(provider, system_prompt="Observe safely.", max_step_tokens=128)

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(reasoner.observe(_task(), ()))

    assert captured.value.code is RuntimeErrorCode.LLM_OUTPUT_INVALID
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"action":"COMPLETE","action":"ESCALATE","tool_name":null,'
        '"arguments":{},"rationale":"duplicate","confidence":0.5}',
        '{"action":"TOOL_CALL","tool_name":"fake_read","arguments":{},'
        '"rationale":"extra","confidence":0.5,"unknown":true}',
    ],
)
def test_malformed_decision_fails_closed_without_repair_or_retry(content: str) -> None:
    provider = FakeLLMProvider(responses=[_response(content), _response(content)])
    reasoner = LLMLoopReasoner(provider, system_prompt="Decide safely.", max_step_tokens=128)

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(reasoner.decide(_task(), _observation(), _plan(), ()))

    assert captured.value.code is RuntimeErrorCode.LLM_OUTPUT_INVALID
    assert "not-json" not in str(captured.value)
    assert len(provider.requests) == 1
