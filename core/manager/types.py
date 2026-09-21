"""Closed, provider-neutral types for AI Manager decisions."""

from __future__ import annotations

from enum import StrEnum


class ManagerDecisionType(StrEnum):
    """The bounded actions an AI Manager may recommend."""

    ASSIGN = "ASSIGN"
    REASSIGN = "REASSIGN"
    PAUSE = "PAUSE"
    ESCALATE = "ESCALATE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    DEFER = "DEFER"
    CANCEL = "CANCEL"


class ManagerReasonCode(StrEnum):
    """Closed, explainable reasons attached to a Manager decision."""

    CAPABILITY_MATCH = "CAPABILITY_MATCH"
    TRUST_RESTRICTION = "TRUST_RESTRICTION"
    AUTONOMY_RESTRICTION = "AUTONOMY_RESTRICTION"
    NO_ELIGIBLE_AGENT = "NO_ELIGIBLE_AGENT"
    WORKLOAD_BALANCING = "WORKLOAD_BALANCING"
    BLOCKER_DETECTED = "BLOCKER_DETECTED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    SECURITY_HOLD = "SECURITY_HOLD"
    DEADLINE_RISK = "DEADLINE_RISK"
