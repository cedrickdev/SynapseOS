"""Tests for the leak-resistant Security error boundary."""

from __future__ import annotations

import pytest

from core.security import SecurityError, SecurityErrorCode


@pytest.mark.parametrize("code", list(SecurityErrorCode))
def test_error_exposes_only_application_owned_messages(code: SecurityErrorCode) -> None:
    """Prevent caller-controlled sensitive data crossing the Security boundary."""
    sensitive_text = "postgres://security:super-secret@db.internal/audit"

    error = SecurityError(code)

    assert error.code is code
    assert error.safe_message
    assert sensitive_text not in str(error)
    with pytest.raises(TypeError):
        SecurityError(code, sensitive_text)  # type: ignore[call-arg]


def test_error_codes_are_closed_and_stable() -> None:
    """Keep scanner and provider failures separately classifiable."""
    assert {code.value for code in SecurityErrorCode} == {
        "INVALID_INPUT",
        "INVALID_ROLE",
        "INACTIVE_AGENT",
        "INVALID_PERMISSION",
        "INVALID_TOOLS",
        "INVALID_SCOPE",
        "SCANNER_FAILURE",
        "PROVIDER_FAILURE",
        "INVALID_ANALYSIS",
        "TIMEOUT",
        "INTERNAL_FAILURE",
    }


def test_error_messages_are_stable_and_security_owned() -> None:
    """Expose bounded public messages without retaining raw exceptions."""
    expected = {
        SecurityErrorCode.INVALID_INPUT: "Security input invalid.",
        SecurityErrorCode.INVALID_ROLE: "Security role invalid.",
        SecurityErrorCode.INACTIVE_AGENT: "Security agent is inactive.",
        SecurityErrorCode.INVALID_PERMISSION: "Security permissions invalid.",
        SecurityErrorCode.INVALID_TOOLS: "Security tools invalid.",
        SecurityErrorCode.INVALID_SCOPE: "Security request scope invalid.",
        SecurityErrorCode.SCANNER_FAILURE: "Security scanner failed.",
        SecurityErrorCode.PROVIDER_FAILURE: "Security provider failed.",
        SecurityErrorCode.INVALID_ANALYSIS: "Security analysis invalid.",
        SecurityErrorCode.TIMEOUT: "Security execution timed out.",
        SecurityErrorCode.INTERNAL_FAILURE: "Security execution failed.",
    }

    for code, safe_message in expected.items():
        error = SecurityError(code)
        assert error.safe_message == safe_message
        assert str(error) == safe_message
        assert error.args == (safe_message,)
