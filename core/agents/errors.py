"""Safe errors raised by the agent domain boundary."""

from __future__ import annotations


class AgentError(Exception):
    """Base error for agent domain failures."""


class AgentOutputValidationError(AgentError):
    """Raised when a response cannot become the requested structured agent value."""

    def __init__(self, expected_type: str) -> None:
        self.expected_type = expected_type
        super().__init__(f"Structured agent output is invalid for {expected_type}.")
