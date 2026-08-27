"""Public contracts for the Phase 5 agents domain."""

from core.agents.agent import Agent
from core.agents.errors import AgentError, AgentOutputValidationError
from core.agents.structured_output import decode_structured_output
from core.agents.types import (
    AgentHistoryEntry,
    AgentOperation,
    AgentProfile,
    AgentReport,
    AgentReportOutcome,
    Decision,
    Observation,
    Plan,
)

__all__ = [
    "Agent",
    "AgentError",
    "AgentHistoryEntry",
    "AgentOperation",
    "AgentOutputValidationError",
    "AgentProfile",
    "AgentReport",
    "AgentReportOutcome",
    "Decision",
    "Observation",
    "Plan",
    "decode_structured_output",
]
