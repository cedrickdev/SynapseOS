"""Stable sanitized failures for the Phase 17 QA workflow boundary."""

from __future__ import annotations

from enum import StrEnum
from traceback import clear_frames
from typing import NoReturn


class QAWorkflowErrorCode(StrEnum):
    """Closed operational failure classifications for the QA workflow stage."""

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
    QAWorkflowErrorCode.INVALID_INPUT: "QA workflow input is invalid.",
    QAWorkflowErrorCode.INVALID_SCOPE: "QA workflow scope is invalid.",
    QAWorkflowErrorCode.INVALID_STATE: "QA workflow task state is invalid.",
    QAWorkflowErrorCode.INVALID_ROLE: "QA workflow agent role is invalid.",
    QAWorkflowErrorCode.INVALID_AGENT: "QA workflow agent is invalid.",
    QAWorkflowErrorCode.TIMEOUT: "QA workflow timed out.",
    QAWorkflowErrorCode.COLLABORATOR_FAILURE: "QA workflow collaborator failed.",
    QAWorkflowErrorCode.PERSISTENCE_FAILURE: "QA workflow persistence failed.",
    QAWorkflowErrorCode.CONCURRENT_MODIFICATION: "QA workflow state changed concurrently.",
    QAWorkflowErrorCode.INTERNAL_FAILURE: "QA workflow internal failure.",
}


class QAWorkflowError(Exception):
    """A leak-resistant QA workflow error with one stable safe message."""

    def __init__(self, code: QAWorkflowErrorCode) -> None:
        if type(code) is not QAWorkflowErrorCode:
            raise TypeError("code must be a QAWorkflowErrorCode")
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)


def _discard_qa_workflow_exception(error: BaseException) -> None:
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


def _raise_qa_workflow_error(code: QAWorkflowErrorCode) -> NoReturn:
    raise QAWorkflowError(code) from None
