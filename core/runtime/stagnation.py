"""Deterministic, bounded stagnation detection for agent loops."""

from __future__ import annotations

import hashlib
import json
from collections import deque

from core.runtime.types import RuntimeDecision, RuntimeVerification
from core.tools import JsonValue, ToolErrorCode

type _Shape = str | list[_Shape] | dict[str, _Shape]


class StagnationDetector:
    """Retain only consecutive SHA-256 progress fingerprints."""

    def __init__(self, window: int) -> None:
        if isinstance(window, bool) or not 2 <= window <= 20:
            raise ValueError("stagnation window must be between 2 and 20")
        self._window = window
        self._digests: deque[str] = deque(maxlen=window)

    @property
    def size(self) -> int:
        """Return the number of bounded fingerprints currently retained."""
        return len(self._digests)

    def observe(
        self,
        decision: RuntimeDecision,
        verification: RuntimeVerification | None,
        tool_error_code: ToolErrorCode | None = None,
    ) -> bool:
        """Record one allowlisted progress shape and report repeated stagnation."""
        canonical = {
            "action": decision.action.value,
            "tool_name": decision.tool_name,
            "argument_shape": _shape(decision.arguments),
            "verification_outcome": verification.outcome.value if verification else None,
            "tool_error_code": tool_error_code.value if tool_error_code else None,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        if self._digests and self._digests[-1] != digest:
            self._digests.clear()
        self._digests.append(digest)
        return len(self._digests) == self._window

    def __repr__(self) -> str:
        return f"StagnationDetector(window={self._window}, digests={tuple(self._digests)!r})"


def _shape(value: JsonValue) -> _Shape:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return [_shape(item) for item in value]
    return {key: _shape(value[key]) for key in sorted(value)}
