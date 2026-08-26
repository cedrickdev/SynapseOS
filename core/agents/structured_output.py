"""Strict decoding for structured agent outputs."""

from __future__ import annotations

import json
from typing import Any, Never

from pydantic import BaseModel, ValidationError

from core.agents.errors import AgentOutputValidationError


def _reject_json_constant(_: str) -> Never:
    """Reject JSON extensions such as NaN and Infinity."""
    raise ValueError("non-finite JSON constants are not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object only when every key occurs once."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def decode_structured_output[ModelT: BaseModel](content: str, model_type: type[ModelT]) -> ModelT:
    """Decode one JSON object into the requested strict Pydantic model."""
    expected_type = model_type.__name__
    parsed: Any = None
    result: ModelT | None = None
    failed = False
    try:
        parsed = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(parsed, dict):
            raise ValueError("structured output root must be an object")
        parsed = None
        result = model_type.model_validate_json(content, strict=True, extra="forbid")
    except (json.JSONDecodeError, ValidationError, ValueError) as raw_error:
        failed = True
        del raw_error

    if failed:
        del content
        del parsed
        del result
        raise AgentOutputValidationError(expected_type) from None

    assert result is not None
    return result
