"""Tests for deterministic, secret-free stagnation detection."""

from __future__ import annotations

from core.runtime import (
    RuntimeAction,
    RuntimeDecision,
    RuntimeVerification,
    RuntimeVerificationOutcome,
    StagnationDetector,
)
from core.tools import ToolErrorCode


def _decision(**changes: object) -> RuntimeDecision:
    values: dict[str, object] = {
        "action": RuntimeAction.TOOL_CALL,
        "tool_name": "read_file",
        "arguments": {"path": "secret-a.txt", "options": {"limit": 10}},
        "rationale": "secret rationale",
        "confidence": 0.8,
    }
    values.update(changes)
    return RuntimeDecision.model_validate(values, strict=True)


def _verification(outcome: RuntimeVerificationOutcome) -> RuntimeVerification:
    return RuntimeVerification(
        outcome=outcome,
        summary="secret tool output",
        progress_made=False,
    )


def test_identical_fingerprints_trigger_only_when_window_is_full() -> None:
    detector = StagnationDetector(window=3)
    decision = _decision()
    verification = _verification(RuntimeVerificationOutcome.CONTINUE)

    assert detector.observe(decision, verification) is False
    assert detector.observe(decision, verification) is False
    assert detector.observe(decision, verification) is True
    assert detector.size == 3


def test_argument_values_do_not_change_shape_or_leak_into_state() -> None:
    detector = StagnationDetector(window=2)

    assert detector.observe(_decision(), None) is False
    assert detector.observe(
        _decision(arguments={"path": "different-secret.txt", "options": {"limit": 999}}), None
    )
    retained = repr(detector)
    assert "secret" not in retained
    assert "different" not in retained
    assert "rationale" not in retained


def test_changed_allowlisted_shape_resets_consecutive_run() -> None:
    detector = StagnationDetector(window=2)
    verification = _verification(RuntimeVerificationOutcome.CONTINUE)

    assert detector.observe(_decision(), verification) is False
    assert detector.observe(_decision(arguments={"path": ["a"]}), verification) is False
    assert detector.observe(_decision(arguments={"path": ["b"]}), verification) is True


def test_verification_outcome_and_error_code_are_fingerprinted() -> None:
    detector = StagnationDetector(window=2)
    decision = _decision()

    assert (
        detector.observe(
            decision, _verification(RuntimeVerificationOutcome.CONTINUE), ToolErrorCode.TOOL_FAILED
        )
        is False
    )
    assert (
        detector.observe(
            decision, _verification(RuntimeVerificationOutcome.COMPLETE), ToolErrorCode.TOOL_FAILED
        )
        is False
    )
    assert (
        detector.observe(
            decision,
            _verification(RuntimeVerificationOutcome.COMPLETE),
            ToolErrorCode.INVALID_INPUT,
        )
        is False
    )
    assert (
        detector.observe(
            decision,
            _verification(RuntimeVerificationOutcome.COMPLETE),
            ToolErrorCode.INVALID_INPUT,
        )
        is True
    )
