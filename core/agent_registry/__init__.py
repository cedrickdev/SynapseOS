"""Phase 28 agent registry and deterministic matching."""

from core.agent_registry.genome import (
    AgentGenomeCapabilitySignal,
    AgentGenomeManagerSignal,
    AgentGenomeManagerSignalMatcher,
)
from core.agent_registry.matcher import AgentMatcher
from core.agent_registry.registry import AgentRegistry, AgentRegistrySource
from core.agent_registry.types import (
    AgentCandidate,
    AgentCapabilitySnapshot,
    AgentCostEstimate,
    AgentMatchingRequest,
    AgentMatchingResult,
    AgentMatchScore,
    RankedAgentMatch,
    RejectedAgentMatch,
)

__all__ = [
    "AgentCandidate",
    "AgentCapabilitySnapshot",
    "AgentCostEstimate",
    "AgentGenomeCapabilitySignal",
    "AgentGenomeManagerSignal",
    "AgentGenomeManagerSignalMatcher",
    "AgentMatcher",
    "AgentRegistry",
    "AgentRegistrySource",
    "AgentMatchingRequest",
    "AgentMatchingResult",
    "AgentMatchScore",
    "RankedAgentMatch",
    "RejectedAgentMatch",
]
