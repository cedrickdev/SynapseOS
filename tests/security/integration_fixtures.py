"""Concrete bounded collaborators for Phase 18 Security integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.llm import LLMProviderError
from core.security import SecurityAgent, SecurityRequest, SecurityScannerReport
from infrastructure.llm import FakeLLMProvider
from tests.security.factories import (
    RecordingSecurityScanner,
    complete_scanner_report,
    security_analysis_response,
    security_request,
)


@dataclass(frozen=True, slots=True)
class ConcreteSecuritySetup:
    """One real Security Agent with observable bounded collaborators."""

    request: SecurityRequest
    agent: SecurityAgent
    provider: FakeLLMProvider
    scanner: RecordingSecurityScanner


def concrete_security_setup(
    tmp_path: Path,
    *,
    request: SecurityRequest | None = None,
    report: SecurityScannerReport | None = None,
    trusted_source_ids: frozenset[str] = frozenset({"security-scanner"}),
    scanner_error: BaseException | None = None,
    provider_error: LLMProviderError | None = None,
) -> ConcreteSecuritySetup:
    """Compose one-shot scanner and provider boundaries without hidden retries."""
    canonical_request = request if request is not None else security_request(tmp_path)
    provider = FakeLLMProvider(
        responses=[security_analysis_response()],
        error=provider_error,
        max_history=1,
    )
    scanner = RecordingSecurityScanner(
        [],
        report=report if report is not None else complete_scanner_report(),
        error=scanner_error,
    )
    agent = SecurityAgent(
        provider,
        scanner,
        trusted_source_ids=trusted_source_ids,
        max_tokens=512,
        provider_timeout_seconds=5.0,
    )
    return ConcreteSecuritySetup(canonical_request, agent, provider, scanner)
