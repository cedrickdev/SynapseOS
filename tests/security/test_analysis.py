"""One-shot structured analysis tests for the Phase 18 Security Agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from core.security import (
    SanitizedSecuritySource,
    SecurityAnalyzer,
    SecurityDecision,
    SecurityError,
    SecurityErrorCode,
    SecurityRequest,
    SecurityScannerReport,
    sanitize_security_source,
)
from infrastructure.llm import FakeLLMProvider
from tests.security.factories import (
    complete_scanner_report,
    scanner_finding,
    security_analysis_response,
    security_request,
    security_request_with_obvious_secret,
)


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
        raise AssertionError("Security timeout did not cancel provider generation")


def _analysis_inputs(
    tmp_path: Path,
) -> tuple[SecurityRequest, SanitizedSecuritySource, SecurityScannerReport]:
    request = security_request(tmp_path)
    return request, sanitize_security_source(request), complete_scanner_report()


def test_analysis_uses_only_sanitized_source_once(tmp_path: Path) -> None:
    """Send one deterministic request containing only bounded sanitized source and metadata."""
    provider = FakeLLMProvider(responses=[security_analysis_response()])
    analyzer = SecurityAnalyzer(provider, max_tokens=2_048, timeout_seconds=1.0)
    request = security_request_with_obvious_secret(tmp_path)
    sanitized = sanitize_security_source(request)
    scanner_report = complete_scanner_report(findings=(scanner_finding(path="config/settings.py"),))

    analysis = asyncio.run(analyzer.analyze(request, sanitized, scanner_report))

    assert analysis.decision is SecurityDecision.PASS
    assert len(provider.requests) == 1
    provider_request = provider.requests[0]
    assert provider_request.temperature == 0.0
    assert provider_request.max_tokens == 2_048
    assert dict(provider_request.metadata) == {}
    assert provider_request.system_prompt is not None
    assert "untrusted data" in provider_request.system_prompt
    assert "unconfirmed" in provider_request.system_prompt
    for responsibility in (
        "secrets",
        "authentication",
        "authorization",
        "injection",
        "input validation",
        "dependencies",
        "dangerous configuration",
    ):
        assert responsibility in provider_request.system_prompt
    assert "PASS|WARN|BLOCK" in provider_request.system_prompt
    assert len(provider_request.messages) == 1
    assert provider_request.messages[0].role is LLMRole.USER
    serialized = provider_request.messages[0].content
    assert "raw-secret-value" not in serialized
    assert request.diff not in serialized
    assert "[REDACTED_SECRET]" in serialized
    assert request.security_id not in serialized
    assert request.profile.system_prompt not in serialized
    assert str(request.execution_context.workspace_root) not in serialized

    payload = json.loads(serialized.removeprefix("Security evidence:\n"))
    assert payload["acceptance_criteria"] == [
        {"criterion_index": 1, "text": "Authorization rejects unauthenticated callers."}
    ]
    assert payload["source"] == {
        "diff": sanitized.diff,
        "files": [item.model_dump(mode="json") for item in sanitized.files],
    }
    assert payload["tests"] == [
        {
            "duration_ms": 1.0,
            "exit_code": 0,
            "profile_id": "pytest",
            "status": "SUCCEEDED",
            "truncated": False,
        }
    ]
    assert payload["local_redaction"] == {
        "complete": True,
        "findings": [item.model_dump(mode="json") for item in sanitized.findings],
    }
    assert payload["qa"] == {
        "confidence": 0.9,
        "criteria": [
            {
                "criterion_index": 1,
                "evidence_profiles": ["pytest"],
                "status": "PASSED",
            }
        ],
        "decision": "PASSED",
        "finding_count": 0,
        "recommendation_count": 0,
    }
    assert payload["scanner"] == scanner_report.model_dump(mode="json")
    assert payload["task_description"] == (
        "Validate the reviewed change using bounded security evidence."
    )
    assert payload["task_title"] == "Harden the authorization boundary"


@pytest.mark.parametrize(
    "response",
    [
        LLMResponse(
            content="not-json",
            model=LLMModelMetadata(provider="fake", model="security-v1"),
        ),
        security_analysis_response(unexpected="marker"),
        security_analysis_response(
            findings=[
                {
                    "category": "authorization",
                    "severity": "HIGH",
                    "path": "src/auth.py",
                    "line_start": 1,
                    "line_end": 1,
                    "explanation": "The provider claims a confirmed issue.",
                    "remediation": "Require authorization.",
                    "confidence": 0.8,
                    "evidence_ids": ["finding-001"],
                    "confirmation": "CONFIRMED",
                }
            ]
        ),
    ],
)
def test_analysis_rejects_malformed_or_unconfirmed_output_without_retry(
    tmp_path: Path,
    response: LLMResponse,
) -> None:
    """Reject invalid, authority-widening, or unsupported provider output without repair."""
    provider = FakeLLMProvider(
        responses=[response, security_analysis_response(SecurityDecision.PASS)]
    )
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512).analyze(
                request,
                sanitized,
                scanner_report,
            )
        )

    assert raised.value.code is SecurityErrorCode.INVALID_ANALYSIS
    assert response.content not in str(raised.value)
    assert len(provider.requests) == 1


def test_analysis_returns_provider_findings_as_unconfirmed_proposals(tmp_path: Path) -> None:
    """Leave evidence trust and final confirmation to the deterministic Task 5 gate."""
    provider = FakeLLMProvider(
        responses=[
            security_analysis_response(
                SecurityDecision.BLOCK,
                findings=[
                    {
                        "category": "authorization",
                        "severity": "HIGH",
                        "path": "src/auth.py",
                        "line_start": 1,
                        "line_end": 1,
                        "explanation": "The authorization boundary may be incomplete.",
                        "remediation": "Require an explicit authorization decision.",
                        "confidence": 0.8,
                        "evidence_ids": ["provider-only-evidence"],
                    }
                ],
                rationale="One provider-only finding requires deterministic review.",
                confidence=0.8,
            )
        ]
    )
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    analysis = asyncio.run(
        SecurityAnalyzer(provider, max_tokens=512).analyze(
            request,
            sanitized,
            scanner_report,
        )
    )

    assert analysis.decision is SecurityDecision.BLOCK
    assert analysis.findings[0].evidence_ids == ("provider-only-evidence",)
    assert not hasattr(analysis.findings[0], "confirmation")
    assert len(provider.requests) == 1


def test_analysis_rejects_oversized_utf8_response_without_retry(tmp_path: Path) -> None:
    """Enforce the 131,072-byte response ceiling before structured decoding."""
    oversized = "é" * 65_537
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=oversized,
                model=LLMModelMetadata(provider="fake", model="security-v1"),
            )
        ]
    )
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512).analyze(
                request,
                sanitized,
                scanner_report,
            )
        )

    assert raised.value.code is SecurityErrorCode.INVALID_ANALYSIS
    assert len(provider.requests) == 1


def test_analysis_accepts_response_at_exact_utf8_byte_limit(tmp_path: Path) -> None:
    """Keep the documented 131,072-byte response endpoint inclusive."""
    response = security_analysis_response()
    padding = 131_072 - len(response.content.encode("utf-8"))
    bounded = LLMResponse(
        content=response.content + (" " * padding),
        model=response.model,
    )
    provider = FakeLLMProvider(responses=[bounded])
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    analysis = asyncio.run(
        SecurityAnalyzer(provider, max_tokens=512).analyze(request, sanitized, scanner_report)
    )

    assert analysis.decision is SecurityDecision.PASS
    assert len(bounded.content.encode("utf-8")) == 131_072
    assert len(provider.requests) == 1


def test_analysis_rejects_forged_provider_response(tmp_path: Path) -> None:
    """Reconstruct provider responses instead of trusting forged Pydantic instances."""
    valid = security_analysis_response()
    forged_model = LLMModelMetadata.model_construct(provider="", model="security-v1")
    forged = LLMResponse.model_construct(content=valid.content, model=forged_model)
    provider = FakeLLMProvider(responses=[forged])
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512).analyze(
                request,
                sanitized,
                scanner_report,
            )
        )

    assert raised.value.code is SecurityErrorCode.INVALID_ANALYSIS
    assert len(provider.requests) == 1


def test_analysis_rejects_mismatched_sanitized_source_before_provider(tmp_path: Path) -> None:
    """Never trust caller-labelled sanitized source that differs from local redaction."""
    request = security_request_with_obvious_secret(tmp_path)
    sanitized = sanitize_security_source(request).model_copy(
        update={"diff": '+token = "raw-secret-value"\n'}
    )
    provider = FakeLLMProvider(responses=[security_analysis_response()])

    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512).analyze(
                request,
                sanitized,
                complete_scanner_report(),
            )
        )

    assert raised.value.code is SecurityErrorCode.INVALID_INPUT
    assert provider.requests == ()


def test_analysis_normalizes_provider_failure_without_retry(tmp_path: Path) -> None:
    """Discard provider diagnostics and preserve exactly-once semantics."""
    marker = "security-provider-secret-marker"
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512).analyze(
                request,
                sanitized,
                scanner_report,
            )
        )

    assert raised.value.code is SecurityErrorCode.PROVIDER_FAILURE
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


def test_analysis_applies_its_own_timeout_without_retry(tmp_path: Path) -> None:
    """Prevent provider generation from outliving the bounded analysis deadline."""
    provider = DelayingProvider()
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512, timeout_seconds=0.01).analyze(
                request,
                sanitized,
                scanner_report,
            )
        )

    assert raised.value.code is SecurityErrorCode.PROVIDER_FAILURE
    assert provider.calls == 1


def test_analysis_propagates_cancellation_and_does_not_close_provider(tmp_path: Path) -> None:
    """Propagate cancellation immediately while preserving caller-owned lifecycle."""
    provider = CancellingProvider()
    request, sanitized, scanner_report = _analysis_inputs(tmp_path)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            SecurityAnalyzer(provider, max_tokens=512).analyze(
                request,
                sanitized,
                scanner_report,
            )
        )

    assert provider.calls == 1
    assert provider.closed is False


@pytest.mark.parametrize("max_tokens", [False, True, 0, -1, 4_097, 1.0])
def test_analysis_rejects_non_integer_or_out_of_range_token_limits(max_tokens: object) -> None:
    """Require one integer generation budget from 1 through 4,096."""
    with pytest.raises(ValueError):
        SecurityAnalyzer(FakeLLMProvider(), max_tokens=max_tokens)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_tokens", [1, 4_096])
def test_analysis_accepts_token_limit_endpoints(max_tokens: int) -> None:
    """Keep both documented token-budget endpoints usable."""
    analyzer = SecurityAnalyzer(FakeLLMProvider(), max_tokens=max_tokens)

    assert vars(analyzer)["_max_tokens"] == max_tokens


@pytest.mark.parametrize(
    "timeout",
    [False, True, 0.0, -1.0, 30.1, float("inf"), float("nan")],
)
def test_analysis_rejects_invalid_timeout_limits(timeout: object) -> None:
    """Reject absent, excessive, non-finite, and boolean provider timeouts."""
    with pytest.raises(ValueError):
        SecurityAnalyzer(
            FakeLLMProvider(),
            max_tokens=512,
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_analysis_accepts_timeout_limit_endpoint() -> None:
    """Keep the documented 30-second timeout endpoint usable."""
    analyzer = SecurityAnalyzer(FakeLLMProvider(), max_tokens=512, timeout_seconds=30.0)

    assert vars(analyzer)["_timeout_seconds"] == 30.0


def test_analysis_rejects_forged_scanner_report_before_provider(tmp_path: Path) -> None:
    """Revalidate scanner reports before exposing their metadata to the provider."""
    request = security_request(tmp_path)
    sanitized = sanitize_security_source(request)
    forged = complete_scanner_report().model_copy(
        update={"findings": (scanner_finding().model_copy(update={"path": "../secret.py"}),)}
    )
    provider = FakeLLMProvider(responses=[security_analysis_response()])

    with pytest.raises(SecurityError) as raised:
        asyncio.run(SecurityAnalyzer(provider, max_tokens=512).analyze(request, sanitized, forged))

    assert raised.value.code is SecurityErrorCode.INVALID_INPUT
    assert provider.requests == ()
