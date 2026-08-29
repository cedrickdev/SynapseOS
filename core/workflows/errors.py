"""Stable sanitized failures for the Phase 16 workflow boundary."""

from __future__ import annotations

from enum import StrEnum


class WorkflowErrorCode(StrEnum):
    """Closed public failure classifications for the Developer–Reviewer workflow."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_STATE = "INVALID_STATE"
    INVALID_ROLE = "INVALID_ROLE"
    INVALID_AGENT = "INVALID_AGENT"
    UNSAFE_HANDOFF = "UNSAFE_HANDOFF"
    TIMEOUT = "TIMEOUT"
    COLLABORATOR_FAILURE = "COLLABORATOR_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


_SAFE_MESSAGES = {
    WorkflowErrorCode.INVALID_INPUT: "Workflow input is invalid.",
    WorkflowErrorCode.INVALID_SCOPE: "Workflow scope is invalid.",
    WorkflowErrorCode.INVALID_STATE: "Workflow task state is invalid.",
    WorkflowErrorCode.INVALID_ROLE: "Workflow agent role is invalid.",
    WorkflowErrorCode.INVALID_AGENT: "Workflow agent is invalid.",
    WorkflowErrorCode.UNSAFE_HANDOFF: "Workflow handoff is unsafe.",
    WorkflowErrorCode.TIMEOUT: "Workflow timed out.",
    WorkflowErrorCode.COLLABORATOR_FAILURE: "Workflow collaborator failed.",
    WorkflowErrorCode.PERSISTENCE_FAILURE: "Workflow persistence failed.",
    WorkflowErrorCode.INTERNAL_FAILURE: "Workflow internal failure.",
}


class WorkflowError(Exception):
    """A leak-resistant workflow error carrying a stable safe message."""

    def __init__(self, code: WorkflowErrorCode) -> None:
        if type(code) is not WorkflowErrorCode:
            raise TypeError("code must be a WorkflowErrorCode")
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)
