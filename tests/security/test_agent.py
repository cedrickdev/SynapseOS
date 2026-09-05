"""Real Security composition with controlled scanner/provider boundaries."""

import asyncio
import time
from contextlib import suppress
from pathlib import Path

import pytest

from core.security import (
    SecurityDecision,
    SecurityError,
    SecurityErrorCode,
    SecurityScannerReport,
    ValidatedSecurityRequest,
)
from tests.security.factories import (
    OTHER_CORRELATION_ID,
    RecordingSecurityProvider,
    RecordingSecurityScanner,
    complete_scanner_report,
    scanner_finding,
    security_request,
    security_request_with_obvious_secret,
)


def test_public_agent_available() -> None:
    import core.security as security

    assert callable(getattr(security, "SecurityAgent", None))


def test_one_shot_order_sanitized_payload_and_no_history(tmp_path: Path) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    scanner = RecordingSecurityScanner(events)
    provider = RecordingSecurityProvider(events)
    agent = SecurityAgent(provider, scanner, trusted_source_ids=frozenset({"security-scanner"}))
    request = security_request_with_obvious_secret(tmp_path)
    result = asyncio.run(agent.run(request))
    assert result.decision is SecurityDecision.BLOCK
    assert events == ["scanner", "provider"]
    payload = provider.requests[0].messages[0].content
    assert "raw-secret-value" not in payload
    assert "[REDACTED_SECRET]" in payload
    assert scanner.requests[0].request == request
    second = asyncio.run(agent.run(security_request(tmp_path)))
    assert second.decision is SecurityDecision.PASS
    assert events == ["scanner", "provider", "scanner", "provider"]
    assert len(provider.requests[1].messages) == 1
    assert "[REDACTED_SECRET]" not in provider.requests[1].messages[0].content
    assert not scanner.closed and not provider.closed


@pytest.mark.parametrize("case", ["scope", "role", "metadata-secret"])
def test_validation_precedes_external_work(tmp_path: Path, case: str) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    scanner = RecordingSecurityScanner(events)
    provider = RecordingSecurityProvider(events)
    request = security_request(tmp_path)
    code = SecurityErrorCode.INVALID_SCOPE
    if case == "scope":
        request = request.model_copy(update={"correlation_id": OTHER_CORRELATION_ID})
    elif case == "role":
        request = request.model_copy(
            update={"profile": request.profile.model_copy(update={"role": "Developer"})}
        )
        code = SecurityErrorCode.INVALID_ROLE
    else:
        request = security_request(tmp_path, task_title='token="private-task-credential"')
        code = SecurityErrorCode.INVALID_INPUT
    with pytest.raises(SecurityError) as raised:
        asyncio.run(SecurityAgent(provider, scanner, trusted_source_ids=frozenset()).run(request))
    assert raised.value.code is code
    assert events == []
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    "case",
    [
        "exception",
        "timeout-exception",
        "malformed",
        "secret",
        "echo",
        "bare-secret",
        "wrong-type",
    ],
)
def test_scanner_failure_never_reaches_provider(tmp_path: Path, case: str) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    request = security_request(tmp_path)
    scanner = RecordingSecurityScanner(events)
    provider = RecordingSecurityProvider(events)
    if case == "exception":
        scanner.error = RuntimeError("private-scanner-diagnostic")
    elif case == "timeout-exception":
        scanner.error = TimeoutError("private-scanner-diagnostic")
    elif case == "malformed":
        scanner.report = complete_scanner_report().model_copy(update={"duration_ms": -1.0})
    elif case == "wrong-type":
        scanner.report = {"complete": True}  # type: ignore[assignment]
    elif case == "bare-secret":
        request = security_request_with_obvious_secret(tmp_path)
        scanner.report = complete_scanner_report(
            findings=(
                scanner_finding(
                    remediation="Rotate raw-secret-value-longer-than-redaction-mask promptly.",
                ),
            )
        )
    else:
        text = (
            'password="private-scanner-credential"'
            if case == "secret"
            else request.affected_files[0].content
        )
        scanner.report = complete_scanner_report(
            findings=(scanner_finding(explanation=text, remediation=text),)
        )
    with pytest.raises(SecurityError) as raised:
        asyncio.run(SecurityAgent(provider, scanner, trusted_source_ids=frozenset()).run(request))
    assert raised.value.code is SecurityErrorCode.SCANNER_FAILURE
    assert events == ["scanner"]
    assert provider.requests == []
    assert "private-" not in str(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None
    assert not scanner.closed and not provider.closed


@pytest.mark.parametrize("trusted", [True, False])
def test_agent_applies_constructor_scanner_trust(tmp_path: Path, trusted: bool) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    scanner = RecordingSecurityScanner(
        events, report=complete_scanner_report(findings=(scanner_finding(),))
    )
    provider = RecordingSecurityProvider(events)
    result = asyncio.run(
        SecurityAgent(
            provider,
            scanner,
            trusted_source_ids=frozenset({"security-scanner"}) if trusted else frozenset(),
        ).run(security_request(tmp_path))
    )
    assert result.decision is (SecurityDecision.BLOCK if trusted else SecurityDecision.WARN)
    assert events == ["scanner", "provider"]


def test_mutable_trust_is_rejected_before_work() -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    with pytest.raises(ValueError):
        SecurityAgent(
            RecordingSecurityProvider(events),
            RecordingSecurityScanner(events),
            trusted_source_ids={"security-scanner"},  # type: ignore[arg-type]
        )
    assert events == []


@pytest.mark.parametrize("boundary", ["scanner", "provider"])
def test_global_timeout_stops_later_work(tmp_path: Path, boundary: str) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    scanner = RecordingSecurityScanner(events, delay=60.0 if boundary == "scanner" else 0.0)
    provider = RecordingSecurityProvider(events, delay=60.0 if boundary == "provider" else 0.0)
    request = security_request(tmp_path, timeout_seconds=0.01)
    with pytest.raises(SecurityError) as raised:
        asyncio.run(SecurityAgent(provider, scanner, trusted_source_ids=frozenset()).run(request))
    assert raised.value.code is SecurityErrorCode.TIMEOUT
    assert events == (["scanner"] if boundary == "scanner" else ["scanner", "provider"])
    assert not scanner.closed and not provider.closed


@pytest.mark.parametrize("boundary", ["scanner", "provider"])
def test_cancellation_propagates_immediately(tmp_path: Path, boundary: str) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    scanner = RecordingSecurityScanner(
        events, error=asyncio.CancelledError() if boundary == "scanner" else None
    )
    provider = RecordingSecurityProvider(
        events, error=asyncio.CancelledError() if boundary == "provider" else None
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            SecurityAgent(provider, scanner, trusted_source_ids=frozenset()).run(
                security_request(tmp_path)
            )
        )
    assert events == (["scanner"] if boundary == "scanner" else ["scanner", "provider"])
    assert not scanner.closed and not provider.closed


def test_provider_failure_is_sanitized_without_retry(tmp_path: Path) -> None:
    from core.security.agent import SecurityAgent

    events: list[str] = []
    scanner = RecordingSecurityScanner(events)
    provider = RecordingSecurityProvider(events, error=RuntimeError("private-provider-diagnostic"))
    with pytest.raises(SecurityError) as raised:
        asyncio.run(
            SecurityAgent(provider, scanner, trusted_source_ids=frozenset()).run(
                security_request(tmp_path)
            )
        )
    assert raised.value.code is SecurityErrorCode.PROVIDER_FAILURE
    assert events == ["scanner", "provider"]
    assert "private-" not in str(raised.value)
    assert raised.value.__context__ is None
    assert not scanner.closed and not provider.closed


@pytest.mark.parametrize("behavior", ["late-return", "swallowed-timeout", "pending-cancel"])
def test_scanner_cannot_continue_after_deadline_or_pending_cancellation(
    tmp_path: Path,
    behavior: str,
) -> None:
    from core.security.agent import SecurityAgent

    class LateScanner(RecordingSecurityScanner):
        async def scan(self, request: ValidatedSecurityRequest) -> SecurityScannerReport:
            self.events.append("scanner")
            self.requests.append(request)
            if behavior == "late-return":
                # Simulate a scanner that fails to yield to the event loop.
                time.sleep(0.02)
            elif behavior == "swallowed-timeout":
                with suppress(asyncio.CancelledError):
                    await asyncio.sleep(60)
            else:
                current = asyncio.current_task()
                assert current is not None
                current.cancel()
            return self.report

    events: list[str] = []
    scanner = LateScanner(events)
    provider = RecordingSecurityProvider(events)
    agent = SecurityAgent(provider, scanner, trusted_source_ids=frozenset())
    if behavior == "pending-cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(agent.run(security_request(tmp_path)))
    else:
        with pytest.raises(SecurityError) as raised:
            asyncio.run(agent.run(security_request(tmp_path, timeout_seconds=0.005)))
        assert raised.value.code is SecurityErrorCode.TIMEOUT
    assert events == ["scanner"]
    assert provider.requests == []
    assert not scanner.closed and not provider.closed
