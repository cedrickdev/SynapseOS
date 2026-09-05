"""Stable sanitized failures for the Phase 18 Security workflow boundary."""

from __future__ import annotations

from enum import StrEnum
from traceback import clear_frames
from typing import NoReturn


class SecurityWorkflowErrorCode(StrEnum):
    """Closed operational failure classifications for the Security workflow."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_STATE = "INVALID_STATE"
    INVALID_ROLE = "INVALID_ROLE"
    INVALID_AGENT = "INVALID_AGENT"
    TIMEOUT = "TIMEOUT"
    COLLABORATOR_FAILURE = "COLLABORATOR_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


_SAFE_MESSAGES = {
    SecurityWorkflowErrorCode.INVALID_INPUT: "Security workflow input is invalid.",
    SecurityWorkflowErrorCode.INVALID_SCOPE: "Security workflow scope is invalid.",
    SecurityWorkflowErrorCode.INVALID_STATE: "Security workflow task state is invalid.",
    SecurityWorkflowErrorCode.INVALID_ROLE: "Security workflow agent role is invalid.",
    SecurityWorkflowErrorCode.INVALID_AGENT: "Security workflow agent is invalid.",
    SecurityWorkflowErrorCode.TIMEOUT: "Security workflow timed out.",
    SecurityWorkflowErrorCode.COLLABORATOR_FAILURE: "Security workflow collaborator failed.",
    SecurityWorkflowErrorCode.PERSISTENCE_FAILURE: "Security workflow persistence failed.",
    SecurityWorkflowErrorCode.CONCURRENT_MODIFICATION: (
        "Security workflow state changed concurrently."
    ),
    SecurityWorkflowErrorCode.INTERNAL_FAILURE: "Security workflow internal failure.",
}


class SecurityWorkflowError(Exception):
    """A leak-resistant Security workflow error with one stable safe message."""

    def __init__(self, code: SecurityWorkflowErrorCode) -> None:
        if type(code) is not SecurityWorkflowErrorCode:
            raise TypeError("code must be a SecurityWorkflowErrorCode")
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)


def _discard_security_workflow_exception(error: BaseException) -> None:
    """Clear traceback links and frames before replacing an internal failure."""
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback = current.__traceback__
        cause = current.__cause__
        context = current.__context__
        current.__traceback__ = None
        current.__cause__ = None
        current.__context__ = None
        if traceback is not None:
            clear_frames(traceback)
        if cause is not None:
            pending.append(cause)
        if context is not None:
            pending.append(context)


def _raise_security_workflow_error(code: SecurityWorkflowErrorCode) -> NoReturn:
    raise SecurityWorkflowError(code) from None
