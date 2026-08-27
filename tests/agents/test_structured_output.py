"""Behavioral tests for strict, confidential agent structured-output decoding."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.agents import AgentOutputValidationError, Decision, Observation, decode_structured_output

MALFORMED_TRACEBACK_MARKER = "traceback-malformed-secret-4f27"
PARSED_TRACEBACK_MARKER = "traceback-parsed-secret-9b61"


class PermissiveOutput(BaseModel):
    """Pydantic's default model configuration ignores unknown fields."""

    summary: str


def assert_safe_validation_error(
    error: AgentOutputValidationError,
    secret_marker: str,
) -> None:
    """Assert that a normalized error exposes no response-derived data."""
    assert secret_marker not in repr(error)
    for attribute_name in dir(error):
        if not attribute_name.startswith("_"):
            assert secret_marker not in repr(getattr(error, attribute_name))

    assert str(error) == "Structured agent output is invalid for Observation."
    assert error.expected_type == "Observation"
    assert error.args == ("Structured agent output is invalid for Observation.",)
    assert vars(error) == {"expected_type": "Observation"}
    assert error.__cause__ is None
    assert error.__context__ is None


def assert_traceback_frame_locals_exclude(
    error: AgentOutputValidationError,
    secret_marker: str,
) -> None:
    """Ensure normalized errors cannot retain response data through tracebacks."""
    traceback = error.__traceback__
    while traceback is not None:
        for value in traceback.tb_frame.f_locals.values():
            assert secret_marker not in repr(value)
        traceback = traceback.tb_next


def test_decode_structured_output_returns_the_requested_pydantic_value() -> None:
    result = decode_structured_output(
        '{"summary":"Repository inspected","facts":[],"uncertainties":[],"risks":[]}',
        Observation,
    )

    assert result == Observation(
        summary="Repository inspected",
        facts=[],
        uncertainties=[],
        risks=[],
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "Repository inspected",
        (
            "```json\n"
            '{"summary":"Repository inspected","facts":[],"uncertainties":[],"risks":[]}'
            "\n```"
        ),
        (
            '{"summary":"Repository inspected","facts":[],"uncertainties":[],"risks":[]}'
            " trailing prose"
        ),
        "[]",
        "NaN",
        "Infinity",
        "-Infinity",
        '{"summary":"First","summary":"Second","facts":[],"uncertainties":[],"risks":[]}',
        '{"summary":123,"facts":[],"uncertainties":[],"risks":[]}',
        (
            '{"summary":"Repository inspected","facts":[],"uncertainties":[],"risks":[],'
            '"extra":"field"}'
        ),
    ],
)
def test_decode_structured_output_rejects_invalid_or_non_object_content(content: str) -> None:
    with pytest.raises(AgentOutputValidationError) as raised:
        decode_structured_output(content, Observation)

    assert raised.value.expected_type == "Observation"


@pytest.mark.parametrize(
    ("content", "secret_marker"),
    [
        ('{"summary":"secret-marker-malformed-4f27', "secret-marker-malformed-4f27"),
        (
            '{"summary":"Repository inspected","facts":"secret-marker-field-9b61",'
            '"uncertainties":[],"risks":[]}',
            "secret-marker-field-9b61",
        ),
    ],
)
def test_decode_structured_output_keeps_response_markers_off_public_errors(
    content: str,
    secret_marker: str,
) -> None:
    with pytest.raises(AgentOutputValidationError) as raised:
        decode_structured_output(content, Observation)

    assert_safe_validation_error(raised.value, secret_marker)


def test_decode_structured_output_keeps_malformed_response_markers_out_of_tracebacks() -> None:
    with pytest.raises(AgentOutputValidationError) as raised:
        decode_structured_output('{"summary":"traceback-malformed-secret-4f27', Observation)

    assert_traceback_frame_locals_exclude(raised.value, MALFORMED_TRACEBACK_MARKER)


def test_decode_structured_output_keeps_parsed_response_markers_out_of_tracebacks() -> None:
    with pytest.raises(AgentOutputValidationError) as raised:
        decode_structured_output(
            '{"summary":"Repository inspected","facts":"traceback-parsed-secret-9b61",'
            '"uncertainties":[],"risks":[]}',
            Observation,
        )

    assert_traceback_frame_locals_exclude(raised.value, PARSED_TRACEBACK_MARKER)


def test_decode_structured_output_forbids_unknown_fields_for_permissive_models() -> None:
    with pytest.raises(AgentOutputValidationError):
        decode_structured_output(
            '{"summary":"Repository inspected","unknown":"field"}',
            PermissiveOutput,
        )


@pytest.mark.parametrize(
    "content",
    [
        (
            '{"choice":"Proceed","rationale":"Validation passed","confidence":"0.5",'
            '"requires_human_approval":false,"evidence":[]}'
        ),
        (
            '{"choice":"Proceed","rationale":"Validation passed","confidence":0.5,'
            '"requires_human_approval":"false","evidence":[]}'
        ),
    ],
)
def test_decode_structured_output_rejects_coercible_json_field_types(content: str) -> None:
    with pytest.raises(AgentOutputValidationError):
        decode_structured_output(content, Decision)
