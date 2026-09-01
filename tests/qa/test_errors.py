"""Tests for the leak-resistant QA error boundary."""

from __future__ import annotations

import pytest

from core.qa import QAError, QAErrorCode


@pytest.mark.parametrize("code", list(QAErrorCode))
def test_error_exposes_only_application_owned_messages(code: QAErrorCode) -> None:
    """Prevent caller-controlled sensitive data from crossing the QA boundary."""
    sensitive_text = "postgres://qa:super-secret@db.internal/quality"

    error = QAError(code)

    assert error.code is code
    assert error.safe_message
    assert sensitive_text not in str(error)
    with pytest.raises(TypeError):
        QAError(code, sensitive_text)  # type: ignore[call-arg]


def test_error_codes_are_closed_and_stable() -> None:
    """Keep operational failures separate from truthful functional QA failures."""
    assert {code.value for code in QAErrorCode} == {
        "INVALID_INPUT",
        "INVALID_ROLE",
        "INACTIVE_AGENT",
        "INVALID_PERMISSION",
        "INVALID_TOOLS",
        "INVALID_SCOPE",
        "TEST_EXECUTION_FAILURE",
        "PROVIDER_FAILURE",
        "INVALID_ANALYSIS",
        "TIMEOUT",
        "INTERNAL_FAILURE",
    }
