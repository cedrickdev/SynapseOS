"""Bounded Phase 17 QA Agent composition."""

from __future__ import annotations

import asyncio
from traceback import clear_frames
from typing import Never

from core.llm import LLMProvider
from core.qa.analysis import QAAnalyzer
from core.qa.decision import build_qa_result
from core.qa.errors import QAError, QAErrorCode
from core.qa.ports import QATestRunner
from core.qa.types import QARequest, QAResult
from core.qa.validation import validate_qa_request


class QAAgent:
    """Execute fresh tests, analyze once, and apply the deterministic QA gate."""

    __slots__ = ("_analyzer", "_test_runner")

    def __init__(
        self,
        provider: LLMProvider,
        test_runner: QATestRunner,
        *,
        max_tokens: int = 2_048,
        provider_timeout_seconds: float = 10.0,
    ) -> None:
        self._analyzer = QAAnalyzer(
            provider,
            max_tokens=max_tokens,
            timeout_seconds=provider_timeout_seconds,
        )
        self._test_runner = test_runner

    async def run(self, request: QARequest) -> QAResult:
        """Run one globally bounded QA invocation without owning collaborators."""
        try:
            outcome = await self._run_once(request)
        except asyncio.CancelledError:
            del request, self
            raise
        del request, self
        if isinstance(outcome, QAError):
            _raise_failure(outcome)
        return outcome

    async def _run_once(self, request: QARequest) -> QAResult | QAError:
        try:
            validated = validate_qa_request(request)
        except QAError as raw_error:
            failure = QAError(raw_error.code)
            _discard_exception(raw_error)
            del raw_error, request, self
            return failure
        request = validated.request
        try:
            async with asyncio.timeout(request.timeout_seconds):
                executions = await self._test_runner.run(validated)
                analysis = await self._analyzer.analyze(request, executions)
                result = build_qa_result(request, executions, analysis)
        except asyncio.CancelledError:
            del validated, request, self
            raise
        except TimeoutError as raw_error:
            failure = QAError(QAErrorCode.TIMEOUT)
            _discard_exception(raw_error)
            del raw_error, validated, request, self
            return failure
        except QAError as raw_error:
            failure = QAError(raw_error.code)
            _discard_exception(raw_error)
            del raw_error, validated, request, self
            return failure
        except Exception as raw_error:
            failure = QAError(QAErrorCode.INTERNAL_FAILURE)
            _discard_exception(raw_error)
            del raw_error, validated, request, self
            return failure
        del executions, analysis, validated, request, self
        return result


def _raise_failure(error: QAError) -> Never:
    raise error


def _discard_exception(error: BaseException) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback = current.__traceback__
        cause = current.__cause__
        context = current.__context__
        current.__traceback__ = None
        current.__cause__ = None
        current.__context__ = None
        if traceback is not None:
            clear_frames(traceback)
        if cause is not None:
            pending.append(cause)
        if context is not None:
            pending.append(context)
    del pending, seen
