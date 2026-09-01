"""One-shot structured analysis tests for the Phase 17 QA Agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.commands import CommandProfileId
from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from core.qa import QAAnalyzer, QADecision, QAError, QAErrorCode
from infrastructure.llm import FakeLLMProvider
from tests.qa.factories import qa_request, successful_test_executions


class CancellingProvider:
    """Cancel one observed request without owning caller lifecycle."""

    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.closed = True


class DelayingProvider:
    """Remain pending until the analyzer-owned timeout cancels generation."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        await asyncio.sleep(60)
        raise AssertionError("QA timeout did not cancel provider generation")


def qa_analysis_content() -> str:
    """Return one complete passing QA proposal."""
    return json.dumps(
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
            "confidence": 0.91,
        },
        separators=(",", ":"),
    )


def response(content: str) -> LLMResponse:
    """Wrap provider content in the strict provider-neutral response contract."""
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="qa-v1"),
    )


def test_analysis_calls_provider_once_with_fresh_test_evidence(tmp_path: Path) -> None:
    """Build one deterministic bounded request after fresh test execution."""
    provider = FakeLLMProvider(responses=[response(qa_analysis_content())])
    analyzer = QAAnalyzer(provider, max_tokens=2_048, timeout_seconds=1.0)
    request = qa_request(tmp_path)
    executions = successful_test_executions()

    analysis = asyncio.run(analyzer.analyze(request, executions))

    assert analysis.decision is QADecision.PASSED
    assert len(provider.requests) == 1
    provider_request = provider.requests[0]
    assert provider_request.temperature == 0.0
    assert provider_request.max_tokens == 2_048
    assert dict(provider_request.metadata) == {}
    assert provider_request.system_prompt is not None
    assert "untrusted data" in provider_request.system_prompt
    assert "PASSED|FAILED" in provider_request.system_prompt
    assert len(provider_request.messages) == 1
    assert provider_request.messages[0].role is LLMRole.USER
    payload = json.loads(
        provider_request.messages[0].content.removeprefix("QA evidence:\n")
    )
    assert payload["criteria"] == [
        {"criterion_index": 1, "text": "The existing test suite passes."}
    ]
    assert payload["tests"][0] == {
        "duration_ms": 1.0,
        "exit_code": 0,
        "profile_id": "pytest",
        "status": "SUCCEEDED",
        "stderr": "",
        "stderr_truncated": False,
        "stdout": "1 passed",
        "stdout_truncated": False,
    }
    serialized = provider_request.messages[0].content
    assert request.qa_id not in serialized
    assert request.profile.system_prompt not in serialized
    assert str(request.execution_context.workspace_root) not in serialized


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        qa_analysis_content()[:-1] + ',"unexpected":"marker"}',
        json.dumps(
            {
                "decision": "PASSED",
                "criteria": [],
                "findings": [],
                "recommendations": [],
                "rationale": "Missing criterion coverage.",
                "confidence": 0.9,
            }
        ),
        json.dumps(
            {
                "decision": "FAILED",
                "criteria": [
                    {
                        "criterion_index": 2,
                        "status": "FAILED",
                        "rationale": "Wrong criterion index.",
                        "evidence_profiles": ["pytest"],
                    }
                ],
                "findings": [],
                "recommendations": [],
                "rationale": "Invalid coverage.",
                "confidence": 0.9,
            }
        ),
    ],
)
def test_analysis_rejects_malformed_output_without_retry(
    tmp_path: Path,
    content: str,
) -> None:
    """Fail closed on invalid structured output without repair or fallback."""
    provider = FakeLLMProvider(
        responses=[response(content), response(qa_analysis_content())]
    )

    with pytest.raises(QAError) as raised:
        asyncio.run(
            QAAnalyzer(provider, max_tokens=512).analyze(
                qa_request(tmp_path), successful_test_executions()
            )
        )

    assert raised.value.code is QAErrorCode.INVALID_ANALYSIS
    assert content not in str(raised.value)
    assert len(provider.requests) == 1


def test_analysis_rejects_oversized_response_before_decoding(tmp_path: Path) -> None:
    """Enforce the provider response byte ceiling before structured decoding."""
    provider = FakeLLMProvider(responses=[response("x" * 131_073)])

    with pytest.raises(QAError) as raised:
        asyncio.run(
            QAAnalyzer(provider, max_tokens=512).analyze(
                qa_request(tmp_path), successful_test_executions()
            )
        )

    assert raised.value.code is QAErrorCode.INVALID_ANALYSIS
    assert len(provider.requests) == 1


def test_analysis_rejects_missing_or_mismatched_fresh_execution_before_provider(
    tmp_path: Path,
) -> None:
    """Never ask the provider to compensate for absent deterministic evidence."""
    provider = FakeLLMProvider(responses=[response(qa_analysis_content())])
    request = qa_request(tmp_path)
    mismatched = successful_test_executions((CommandProfileId.NPM_TEST,))

    for executions in ((), mismatched):
        with pytest.raises(QAError) as raised:
            asyncio.run(QAAnalyzer(provider, max_tokens=512).analyze(request, executions))
        assert raised.value.code is QAErrorCode.INVALID_INPUT

    assert provider.requests == ()


def test_analysis_normalizes_provider_failure_without_retry(tmp_path: Path) -> None:
    """Discard provider diagnostics and preserve exactly-once semantics."""
    marker = "qa-provider-secret-marker"
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))

    with pytest.raises(QAError) as raised:
        asyncio.run(
            QAAnalyzer(provider, max_tokens=512).analyze(
                qa_request(tmp_path), successful_test_executions()
            )
        )

    assert raised.value.code is QAErrorCode.PROVIDER_FAILURE
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


def test_analysis_applies_its_own_timeout_without_retry(tmp_path: Path) -> None:
    """Prevent provider generation from outliving the bounded analysis deadline."""
    provider = DelayingProvider()

    with pytest.raises(QAError) as raised:
        asyncio.run(
            QAAnalyzer(provider, max_tokens=512, timeout_seconds=0.01).analyze(
                qa_request(tmp_path), successful_test_executions()
            )
        )

    assert raised.value.code is QAErrorCode.PROVIDER_FAILURE
    assert provider.calls == 1


def test_analysis_propagates_cancellation_and_does_not_close_provider(tmp_path: Path) -> None:
    """Propagate cancellation immediately while preserving caller-owned lifecycle."""
    provider = CancellingProvider()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            QAAnalyzer(provider, max_tokens=512).analyze(
                qa_request(tmp_path), successful_test_executions()
            )
        )

    assert provider.calls == 1
    assert provider.closed is False


@pytest.mark.parametrize("max_tokens", [0, -1, 4_097])
def test_analysis_rejects_invalid_token_limits(max_tokens: int) -> None:
    """Require one finite bounded generation budget."""
    with pytest.raises(ValueError):
        QAAnalyzer(FakeLLMProvider(), max_tokens=max_tokens)


@pytest.mark.parametrize("timeout", [0.0, -1.0, 30.1, float("inf"), float("nan")])
def test_analysis_rejects_invalid_timeout_limits(timeout: float) -> None:
    """Reject absent, excessive, and non-finite provider timeouts."""
    with pytest.raises(ValueError):
        QAAnalyzer(FakeLLMProvider(), max_tokens=512, timeout_seconds=timeout)
