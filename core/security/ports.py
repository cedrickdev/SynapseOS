"""Provider-neutral ports for bounded Phase 18 security scanners."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.security.types import SecurityScannerReport
from core.security.validation import ValidatedSecurityRequest


@runtime_checkable
class SecurityScannerPort(Protocol):
    """One-shot injected scanner that returns sanitized metadata only."""

    async def scan(self, request: ValidatedSecurityRequest) -> SecurityScannerReport:
        """Scan one validated request exactly once."""
        ...
