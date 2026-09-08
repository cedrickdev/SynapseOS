"""Concrete Phase 18 Security Agent integration tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.security import SecurityDecision
from tests.security.factories import complete_scanner_report, scanner_finding
from tests.security.integration_fixtures import concrete_security_setup


@pytest.mark.parametrize(
    ("trusted", "expected"),
    [
        (True, SecurityDecision.BLOCK),
        (False, SecurityDecision.WARN),
    ],
)
def test_concrete_security_agent_applies_deterministic_trust_gate(
    tmp_path: Path,
    trusted: bool,
    expected: SecurityDecision,
) -> None:
    """Let trusted scanner evidence veto while untrusted evidence stays suspected."""
    setup = concrete_security_setup(
        tmp_path,
        report=complete_scanner_report(findings=(scanner_finding(),)),
        trusted_source_ids=(frozenset({"security-scanner"}) if trusted else frozenset()),
    )

    result = asyncio.run(setup.agent.run(setup.request))

    assert result.decision is expected
    assert len(setup.scanner.requests) == 1
    assert len(setup.provider.requests) == 1


def test_concrete_security_agent_passes_clean_complete_evidence(tmp_path: Path) -> None:
    """Produce PASS only from clean complete evidence and one provider analysis."""
    setup = concrete_security_setup(tmp_path)

    result = asyncio.run(setup.agent.run(setup.request))

    assert result.decision is SecurityDecision.PASS
    assert len(setup.scanner.requests) == 1
    assert len(setup.provider.requests) == 1
    assert not setup.scanner.closed
