"""Contract tests for the injected Phase 18 Security scanner port."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.security import SecurityScannerReport, validate_security_request
from core.security.ports import SecurityScannerPort
from core.security.validation import ValidatedSecurityRequest
from tests.security.factories import complete_scanner_report, security_request


class RecordingSecurityScanner:
    """Minimal scanner double that records one canonical request."""

    def __init__(self, report: SecurityScannerReport) -> None:
        self.report = report
        self.requests: list[ValidatedSecurityRequest] = []

    async def scan(self, request: ValidatedSecurityRequest) -> SecurityScannerReport:
        self.requests.append(request)
        return self.report


def test_scanner_port_accepts_one_validated_request_and_returns_metadata_report(
    tmp_path: Path,
) -> None:
    validated = validate_security_request(security_request(tmp_path))
    expected = complete_scanner_report()
    scanner = RecordingSecurityScanner(expected)

    assert isinstance(scanner, SecurityScannerPort)
    result = asyncio.run(scanner.scan(validated))

    assert scanner.requests == [validated]
    assert result is expected
    assert result.model_dump() == {
        "suite_id": "security-scanner",
        "findings": (),
        "complete": True,
        "truncated": False,
        "duration_ms": 1.0,
    }
    assert not hasattr(scanner, "close")
    assert not hasattr(scanner, "retry")
