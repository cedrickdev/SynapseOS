"""Stable content-free control API failures."""

from __future__ import annotations

from enum import StrEnum


class ControlErrorCode(StrEnum):
    FORBIDDEN = "CONTROL_FORBIDDEN"
    NOT_FOUND = "CONTROL_NOT_FOUND"
    CONFLICT = "CONTROL_CONFLICT"
    QUEUE_FULL = "CONTROL_QUEUE_FULL"
    UNAVAILABLE = "CONTROL_UNAVAILABLE"


class ControlError(RuntimeError):
    def __init__(self, code: ControlErrorCode) -> None:
        self.code = code
        super().__init__(code.value)
