"""Confidentiality tests for the QA provider boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import TracebackType

from core.llm import LLMProviderError
from core.qa import QAAnalyzer, QAError, QAErrorCode
from infrastructure.llm import FakeLLMProvider
from tests.qa.factories import qa_request, successful_test_executions


def _assert_traceback_excludes_marker(traceback: TracebackType | None, marker: str) -> None:
    while traceback is not None:
        assert all(marker not in repr(value) for value in traceback.tb_frame.f_locals.values())
        traceback = traceback.tb_next


def _capture_provider_failure(tmp_path: Path) -> tuple[QAError, int]:
    marker = "qa-sensitive-provider-frame-marker"
    request = qa_request(tmp_path, diff=marker)
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))
    analyzer = QAAnalyzer(provider, max_tokens=512)
    try:
        asyncio.run(analyzer.analyze(request, successful_test_executions()))
    except QAError as error:
        calls = len(provider.requests)
        del marker, request, provider, analyzer
        return error, calls
    raise AssertionError("provider failure should be sanitized")


def test_provider_failure_retains_no_sensitive_context_or_traceback_values(
    tmp_path: Path,
) -> None:
    """Remove raw prompts, requests, responses, and provider errors before raising."""
    error, calls = _capture_provider_failure(tmp_path)

    assert error.code is QAErrorCode.PROVIDER_FAILURE
    assert error.__cause__ is None
    assert error.__context__ is None
    assert calls == 1
    marker = "qa-sensitive-provider-frame-marker"
    assert marker not in str(error)
    _assert_traceback_excludes_marker(error.__traceback__, marker)


def test_analyzer_instance_retains_no_request_response_or_result_history() -> None:
    """Keep only the injected provider and immutable execution limits."""
    analyzer = QAAnalyzer(FakeLLMProvider(), max_tokens=512)

    assert set(vars(analyzer)) == {"_provider", "_max_tokens", "_timeout_seconds"}
