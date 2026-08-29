"""One-shot structured analysis tests for the Reviewer Agent."""

from __future__ import annotations

import asyncio
import json
from types import TracebackType

import pytest

from core.enums import Permission
from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from core.reviewer import (
    ReviewAnalysis,
    ReviewAnalyzer,
    ReviewDecision,
    ReviewerError,
    ReviewerErrorCode,
    ReviewerRequest,
    ValidatedReviewerRequest,
)
from core.reviewer import analysis as analysis_module
from infrastructure.llm import FakeLLMProvider
from tests.reviewer.factories import request_values


class CancellingProvider:
    """Provider double that observes one request before cancelling it."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Cancel without turning cancellation into a provider failure."""
        del request
        self.calls += 1
        raise asyncio.CancelledError


class DelayingProvider:
    """Provider double that waits long enough for reviewer-owned timeout."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Remain pending until the caller-owned timeout cancels this call."""
        del request
        self.calls += 1
        await asyncio.sleep(60)
        raise AssertionError("reviewer timeout did not cancel provider generation")


def _request(**overrides: object) -> ReviewerRequest:
    values = request_values()
    values.update(overrides)
    return ReviewerRequest.model_validate(values)


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="deterministic-v1"),
    )


def _valid_content() -> str:
    return (
        '{"decision":"APPROVED","findings":[],"rationale":'
        '"All supplied evidence supports approval.","confidence":0.91}'
    )


def _assert_exception_excludes_marker(error: BaseException, marker: str) -> None:
    """Inspect public exception links and traceback locals for confidential content."""
    current: BaseException | None = error
    while current is not None:
        assert marker not in str(current)
        assert marker not in repr(current)
        assert marker not in repr(current.args)
        assert marker not in repr(vars(current))
        _assert_traceback_excludes_marker(current.__traceback__, marker)
        current = current.__cause__ or current.__context__


def _assert_traceback_excludes_marker(traceback: TracebackType | None, marker: str) -> None:
    """Inspect every traceback frame local without retaining the inspected values."""
    while traceback is not None:
        for value in traceback.tb_frame.f_locals.values():
            assert marker not in repr(value)
        traceback = traceback.tb_next


def _capture_provider_failure() -> tuple[ReviewerError, int]:
    marker = "provider-boundary-secret-marker"
    request = _request(diff=marker)
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))
    analyzer = ReviewAnalyzer(provider, max_tokens=512)
    captured: ReviewerError | None = None
    try:
        asyncio.run(analyzer.analyze(request))
    except ReviewerError as error:
        captured = error
        calls = len(provider.requests)
        del marker, request, provider, analyzer
        return captured, calls
    raise AssertionError("provider failure should be sanitized")


def _capture_validation_failure() -> tuple[ReviewerError, int]:
    marker = "validation-boundary-secret-marker"
    request = _request(diff="safe diff")
    provider = FakeLLMProvider(responses=[_response(marker)])
    analyzer = ReviewAnalyzer(provider, max_tokens=512)
    captured: ReviewerError | None = None
    try:
        asyncio.run(analyzer.analyze(request))
    except ReviewerError as error:
        captured = error
        calls = len(provider.requests)
        del marker, request, provider, analyzer
        return captured, calls
    raise AssertionError("invalid structured output should be sanitized")


def test_analysis_makes_one_strict_bounded_request_from_canonical_evidence() -> None:
    """Prevent prompt, metadata, or retry changes from leaking submitted evidence."""
    provider = FakeLLMProvider(responses=[_response(_valid_content())])
    analyzer = ReviewAnalyzer(provider, max_tokens=512)
    request = _request()

    analysis = asyncio.run(analyzer.analyze(request))

    assert analysis == ReviewAnalysis(
        decision=ReviewDecision.APPROVED,
        findings=(),
        rationale="All supplied evidence supports approval.",
        confidence=0.91,
    )
    assert len(provider.requests) == 1
    provider_request = provider.requests[0]
    assert provider_request.system_prompt is not None
    assert "untrusted data" in provider_request.system_prompt
    assert (
        "decision,findings[{category,severity,rationale,path,line,recommendation}],rationale,confidence"
        in provider_request.system_prompt
    )
    assert "APPROVED|CHANGES_REQUESTED" in provider_request.system_prompt
    assert "INFO|LOW|MEDIUM|HIGH|CRITICAL" in provider_request.system_prompt
    assert len(provider_request.messages) == 1
    assert provider_request.messages[0].role is LLMRole.USER
    assert provider_request.temperature == 0.0
    assert provider_request.max_tokens == 512
    assert dict(provider_request.metadata) == {}

    payload = json.loads(provider_request.messages[0].content.removeprefix("Review evidence:\n"))
    assert payload == {
        "acceptance_criteria": ["The existing test suite passes."],
        "checks": [
            {
                "category": "TEST",
                "exit_code": 0,
                "profile_id": "pytest",
                "status": "SUCCEEDED",
                "truncated": False,
            }
        ],
        "developer_report": {
            "details": ["The focused test suite passed."],
            "next_actions": [],
            "outcome": "SUCCEEDED",
            "summary": "Implemented the requested change.",
        },
        "diff": "--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n-return 0\n+return a + b\n",
        "task_description": "Correct the faulty addition implementation.",
        "task_title": "Correct addition",
    }
    serialized_evidence = provider_request.messages[0].content
    assert request.reviewer_id not in serialized_evidence
    assert request.profile.system_prompt not in serialized_evidence


def test_analysis_uses_preflight_canonical_request_instead_of_mutable_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent mutable caller values from becoming provider prompt evidence."""
    canonical = _request(task_title="Canonical title")
    mutable = _request(task_title="Mutable title")
    validated = ValidatedReviewerRequest(
        request=canonical,
        permissions=frozenset({Permission.FILESYSTEM_READ}),
    )
    provider = FakeLLMProvider(responses=[_response(_valid_content())])
    monkeypatch.setattr(analysis_module, "validate_reviewer_request", lambda _: validated)

    asyncio.run(ReviewAnalyzer(provider, max_tokens=512).analyze(mutable))

    content = provider.requests[0].messages[0].content
    assert "Canonical title" in content
    assert "Mutable title" not in content


@pytest.mark.parametrize(
    "content",
    [
        "not-json-reviewer-response-marker",
        (
            '{"decision":"APPROVED","findings":[],"rationale":"Valid rationale.",'
            '"confidence":0.9,"unexpected":"sensitive-extra-field-marker"}'
        ),
        json.dumps(
            {
                "decision": "CHANGES_REQUESTED",
                "findings": [
                    {
                        "category": "correctness",
                        "severity": "LOW",
                        "rationale": "A bounded rationale.",
                        "recommendation": "Make a bounded change.",
                    }
                    for _ in range(65)
                ],
                "rationale": "Too many findings.",
                "confidence": 0.8,
            }
        ),
        (
            '{"decision":"CHANGES_REQUESTED","findings":[{"category":"security",'
            '"severity":"HIGH","rationale":"Absolute path marker.",'
            '"path":"/private/sensitive-reviewer-marker.py","line":1,'
            '"recommendation":"Use a relative path."}],"rationale":"Path is invalid.",'
            '"confidence":0.8}'
        ),
    ],
)
def test_analysis_fails_closed_for_invalid_provider_output_without_retry(content: str) -> None:
    """Prevent malformed or unsafe model output from being repaired or exposed."""
    provider = FakeLLMProvider(responses=[_response(content), _response(_valid_content())])

    with pytest.raises(ReviewerError) as raised:
        asyncio.run(ReviewAnalyzer(provider, max_tokens=512).analyze(_request()))

    assert raised.value.code is ReviewerErrorCode.INVALID_ANALYSIS
    assert content not in str(raised.value)
    assert "sensitive-reviewer-marker" not in str(raised.value)
    assert len(provider.requests) == 1


def test_analysis_normalizes_provider_failure_without_provider_error_content() -> None:
    """Prevent provider diagnostics from crossing the reviewer error boundary."""
    provider_marker = "provider-secret-reviewer-marker"
    provider = FakeLLMProvider(
        error=LLMProviderError(provider_marker, provider="fake"),
    )

    with pytest.raises(ReviewerError) as raised:
        asyncio.run(ReviewAnalyzer(provider, max_tokens=512).analyze(_request()))

    assert raised.value.code is ReviewerErrorCode.PROVIDER_FAILURE
    assert provider_marker not in str(raised.value)
    assert len(provider.requests) == 1


def test_provider_failure_retains_no_raw_exception_context_or_sensitive_traceback_values() -> None:
    """Prevent provider errors, prompt evidence, or raw request data surviving sanitization."""
    error, calls = _capture_provider_failure()

    assert error.code is ReviewerErrorCode.PROVIDER_FAILURE
    assert error.__cause__ is None
    assert error.__context__ is None
    assert calls == 1
    _assert_exception_excludes_marker(error, "provider-boundary-secret-marker")


def test_validation_failure_retains_no_raw_exception_context_or_sensitive_traceback_values() -> (
    None
):
    """Prevent invalid response content surviving the reviewer error boundary."""
    error, calls = _capture_validation_failure()

    assert error.code is ReviewerErrorCode.INVALID_ANALYSIS
    assert error.__cause__ is None
    assert error.__context__ is None
    assert calls == 1
    _assert_exception_excludes_marker(error, "validation-boundary-secret-marker")


def test_analysis_rejects_response_larger_than_the_utf8_ceiling_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent oversized provider content from reaching the JSON decoder."""
    provider = FakeLLMProvider(responses=[_response("x" * 131_073)])
    monkeypatch.setattr(
        analysis_module,
        "decode_structured_output",
        lambda *_: (_ for _ in ()).throw(AssertionError("decoder must not run")),
    )

    with pytest.raises(ReviewerError) as raised:
        asyncio.run(ReviewAnalyzer(provider, max_tokens=512).analyze(_request()))

    assert raised.value.code is ReviewerErrorCode.INVALID_ANALYSIS
    assert len(provider.requests) == 1


def test_analysis_normalizes_the_reviewer_owned_provider_timeout_without_retry() -> None:
    """Prevent a delayed provider from outliving the finite reviewer-owned deadline."""
    provider = DelayingProvider()

    with pytest.raises(ReviewerError) as raised:
        asyncio.run(
            ReviewAnalyzer(provider, max_tokens=512, timeout_seconds=0.01).analyze(_request())
        )

    assert raised.value.code is ReviewerErrorCode.PROVIDER_FAILURE
    assert provider.calls == 1


def test_analysis_propagates_cancellation_after_one_attempt() -> None:
    """Prevent cancellation from being mistaken for a safe reviewer failure."""
    provider = CancellingProvider()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ReviewAnalyzer(provider, max_tokens=512).analyze(_request()))

    assert provider.calls == 1


@pytest.mark.parametrize("max_tokens", [0, -1, 4097])
def test_analysis_rejects_invalid_token_limits(max_tokens: int) -> None:
    """Prevent a Reviewer analysis from requesting no limit or an excessive limit."""
    with pytest.raises(ValueError):
        ReviewAnalyzer(FakeLLMProvider(), max_tokens=max_tokens)


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, 30.1, float("inf"), float("nan")])
def test_analysis_rejects_invalid_timeout_limits(timeout_seconds: float) -> None:
    """Prevent unbounded or non-finite provider wait time from entering review analysis."""
    with pytest.raises(ValueError):
        ReviewAnalyzer(FakeLLMProvider(), max_tokens=512, timeout_seconds=timeout_seconds)
