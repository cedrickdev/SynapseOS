"""Shared provider-neutral Sentinel signal vocabulary."""

from enum import StrEnum


class SentinelRiskSignal(StrEnum):
    """Closed risk signals that independent Sentinel agents may report."""

    MISLEADING_RESULT = "MISLEADING_RESULT"
    SUSPICIOUS_COORDINATION = "SUSPICIOUS_COORDINATION"
    EVALUATION_GAMING = "EVALUATION_GAMING"
    POLICY_EVASION = "POLICY_EVASION"
    MEMORY_POISONING = "MEMORY_POISONING"
    COLLUSION_PATTERN = "COLLUSION_PATTERN"
    UNEXPLAINED_RESULT_SHIFT = "UNEXPLAINED_RESULT_SHIFT"
