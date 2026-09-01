"""Composition tests for the bounded Phase 17 QA Agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.llm import LLMModelMetadata, LLMRequest, LLMResponse
from core.qa import QAAgent, QADecision, QAError, QAErrorCode, QATestExecution, ValidatedQARequest
from infrastructure.llm import FakeLLMProvider
from tests.qa.factories import qa_request, successful_test_executions


class RecordingRunner:
    """Record validated invocations and return one predetermined outcome."""

    def __init__(
        self,
        executions: tuple[QATestExecution, ...] = successful_test_executions(),
        *,
        error: BaseException | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.executions = executions
        self.error = error
        self.delay_seconds = delay_seconds
        self.requests: list[ValidatedQARequest] = []
        self.closed = False

    async def run(self, request: ValidatedQARequest) -> tuple[QATestExecution, ...]:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self.executions

    async def close(self) -> None:
        self.closed = True


class ObservingProvider:
    """Assert that fresh test execution occurred before provider analysis."""

    def __init__(self, runner: RecordingRunner) -> None:
        self.runner = runner
        self.calls = 0
        self.closed = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert len(self.runner.requests) == 1
        self.calls += 1
        del request
        return passing_response()

    async def close(self) -> None:
        self.closed = True


def passing_response() -> LLMResponse:
    """Return one complete strict provider proposal."""
    content = json.dumps(
        {
            "decision": "PASSED",
            "criteria": [
                {
                    "criterion_index": 1,
                    "status": "PASSED",
                    "rationale": "The required profile passed.",
                    "evidence_profiles": ["pytest"],
                }
            ],
            "findings": [],
            "recommendations": [],
            "rationale": "Fresh deterministic evidence supports the criterion.",
            "confidence": 0.90,
        },
        separators=(",", ":"),
    )
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="qa-v1"),
    )


def test_agent_runs_validation_then_tests_then_one_analysis(tmp_path: Path) -> None:
    """Compose one bounded QA pass in its deterministic order."""
    runner = RecordingRunner()
    provider = ObservingProvider(runner)
    agent = QAAgent(provider, runner, max_tokens=512)

    result = asyncio.run(agent.run(qa_request(tmp_path)))

    assert result.decision is QADecision.PASSED
    assert len(runner.requests) == 1
    assert provider.calls == 1
    assert runner.closed is False
    assert provider.closed is False


def test_agent_rejects_invalid_scope_before_runner_or_provider(tmp_path: Path) -> None:
    """Perform no external action before canonical fail-closed preflight."""
    runner = RecordingRunner()
    provider = FakeLLMProvider(responses=[passing_response()])
    invalid = qa_request(tmp_path).model_copy(update={"qa_id": "qa-02"})

    with pytest.raises(QAError):
        asyncio.run(QAAgent(provider, runner).run(invalid))

    assert runner.requests == []
    assert provider.requests == ()


def test_agent_enforces_global_timeout_before_provider(tmp_path: Path) -> None:
    """Bound the complete test-plus-analysis operation by the request deadline."""
    runner = RecordingRunner(delay_seconds=60.0)
    provider = FakeLLMProvider(responses=[passing_response()])
    request = qa_request(tmp_path, timeout_seconds=0.01)

    with pytest.raises(QAError) as raised:
        asyncio.run(QAAgent(provider, runner).run(request))

    assert raised.value.code is QAErrorCode.TIMEOUT
    assert len(runner.requests) == 1
    assert provider.requests == ()


def test_agent_propagates_cancellation_without_provider_or_close(tmp_path: Path) -> None:
    """Stop immediately and preserve ownership when test execution is cancelled."""
    runner = RecordingRunner(error=asyncio.CancelledError())
    provider = FakeLLMProvider(responses=[passing_response()])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(QAAgent(provider, runner).run(qa_request(tmp_path)))

    assert len(runner.requests) == 1
    assert provider.requests == ()
    assert runner.closed is False


def test_agent_normalizes_unexpected_runner_failure_without_retry(tmp_path: Path) -> None:
    """Do not leak diagnostics or rerun after an unexpected collaborator failure."""
    marker = "qa-runner-secret-marker"
    runner = RecordingRunner(error=RuntimeError(marker))
    provider = FakeLLMProvider(responses=[passing_response()])

    with pytest.raises(QAError) as raised:
        asyncio.run(QAAgent(provider, runner).run(qa_request(tmp_path)))

    assert raised.value.code is QAErrorCode.INTERNAL_FAILURE
    assert marker not in str(raised.value)
    assert len(runner.requests) == 1
    assert provider.requests == ()


def test_agent_retains_no_request_response_result_or_history() -> None:
    """Keep only the two injected collaborators needed by the current invocation."""
    agent = QAAgent(FakeLLMProvider(), RecordingRunner())

    assert not hasattr(agent, "__dict__")
    for name in ("request", "result", "history", "retry", "close", "write", "merge"):
        assert not hasattr(agent, name)
