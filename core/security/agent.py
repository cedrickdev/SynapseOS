"""One-shot Security composition with deterministic veto and bounded failures."""

from __future__ import annotations

import asyncio

from core.llm import LLMProvider
from core.security.analysis import SecurityAnalyzer, _discard_exception
from core.security.decision import (
    build_security_result,
    contains_sensitive_text,
    sensitive_source_text,
)
from core.security.errors import SecurityError, SecurityErrorCode
from core.security.ports import SecurityScannerPort
from core.security.redaction import contains_obvious_secret, sanitize_security_source
from core.security.types import SecurityRequest, SecurityResult, SecurityScannerReport
from core.security.validation import validate_security_request


class SecurityAgent:
    """Validate, sanitize, scan once, analyze once, and apply deterministic trust."""

    __slots__ = ("_analyzer", "_scanner", "_trusted_source_ids")

    def __init__(
        self,
        provider: LLMProvider,
        scanner: SecurityScannerPort,
        *,
        trusted_source_ids: frozenset[str],
        max_tokens: int = 2_048,
        provider_timeout_seconds: float = 10.0,
    ) -> None:
        if type(trusted_source_ids) is not frozenset or any(
            type(item) is not str for item in trusted_source_ids
        ):
            raise ValueError("Security trust configuration must be an immutable set of source IDs")
        self._trusted_source_ids = trusted_source_ids
        self._scanner = scanner
        self._analyzer = SecurityAnalyzer(
            provider,
            max_tokens=max_tokens,
            timeout_seconds=provider_timeout_seconds,
        )

    async def run(self, request: SecurityRequest) -> SecurityResult:
        """Run without retries, history, or ownership of collaborator lifecycle."""
        try:
            outcome = await self._run_once(request)
        except asyncio.CancelledError:
            del request, self
            raise
        del request, self
        if isinstance(outcome, SecurityError):
            raise outcome from None
        return outcome

    async def _run_once(self, request: SecurityRequest) -> SecurityResult | SecurityError:
        phase = SecurityErrorCode.INVALID_INPUT
        deadline: asyncio.Timeout | None = None
        try:
            validated = validate_security_request(request)
            request = validated.request
            if any(
                contains_obvious_secret(value)
                for value in (
                    request.task_title,
                    request.task_description,
                    *request.acceptance_criteria,
                )
            ):
                raise ValueError("Security metadata contains a credential")
            phase = SecurityErrorCode.INTERNAL_FAILURE
            deadline = asyncio.timeout(request.timeout_seconds)
            async with deadline:
                source = sanitize_security_source(request)
                _checkpoint(deadline)
                phase = SecurityErrorCode.SCANNER_FAILURE
                raw_report = await self._scanner.scan(validated)
                _checkpoint(deadline)
                if type(raw_report) is not SecurityScannerReport:
                    raise ValueError("Invalid scanner report")
                report = SecurityScannerReport.model_validate(raw_report.model_dump(warnings=False))
                _validate_scanner_disclosure(report, request)
                _checkpoint(deadline)
                phase = SecurityErrorCode.INTERNAL_FAILURE
                analysis = await self._analyzer.analyze(request, source, report)
                _checkpoint(deadline)
                result = build_security_result(
                    request,
                    source,
                    report,
                    analysis,
                    trusted_source_ids=self._trusted_source_ids,
                )
                _checkpoint(deadline)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if deadline is not None and _deadline_elapsed(deadline):
                code = SecurityErrorCode.TIMEOUT
            elif phase is SecurityErrorCode.SCANNER_FAILURE:
                code = phase
            else:
                code = error.code if isinstance(error, SecurityError) else phase
            failure = SecurityError(code)
            _discard_exception(error)
        return failure


def _deadline_elapsed(deadline: asyncio.Timeout) -> bool:
    when = deadline.when()
    return deadline.expired() or (when is not None and asyncio.get_running_loop().time() >= when)


def _checkpoint(deadline: asyncio.Timeout) -> None:
    if _deadline_elapsed(deadline):
        raise SecurityError(SecurityErrorCode.TIMEOUT)
    current = asyncio.current_task()
    if current is not None and current.cancelling():
        raise asyncio.CancelledError


def _validate_scanner_disclosure(report: SecurityScannerReport, request: SecurityRequest) -> None:
    sources = sensitive_source_text(request)
    texts = [report.suite_id]
    for finding in report.findings:
        texts.extend(
            (finding.category, finding.explanation, finding.remediation, finding.path or "")
        )
        texts.extend(
            value for ref in finding.evidence for value in (ref.source_id, ref.evidence_id)
        )
    if any(contains_sensitive_text(text, sources) for text in texts):
        raise ValueError("Scanner report contains source-sensitive metadata")
