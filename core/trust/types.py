"""Closed vocabulary for immutable Agent Trust history."""

from enum import StrEnum


class TrustClass(StrEnum):
    """Policy-neutral labels stored alongside a Trust snapshot."""

    HIGH = "HIGH"
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    LOW = "LOW"


class TrustDimension(StrEnum):
    """Explainable operational trust dimensions."""

    IDENTITY = "IDENTITY"
    PERMISSION_HYGIENE = "PERMISSION_HYGIENE"
    RELIABILITY = "RELIABILITY"
    REVIEW_HISTORY = "REVIEW_HISTORY"
    SECURITY_HISTORY = "SECURITY_HISTORY"
    POLICY_COMPLIANCE = "POLICY_COMPLIANCE"
    ANOMALY_HISTORY = "ANOMALY_HISTORY"
    ROLLBACK_RATE = "ROLLBACK_RATE"
    INCIDENT_HISTORY = "INCIDENT_HISTORY"
    AUDIT_COMPLETENESS = "AUDIT_COMPLETENESS"


class TrustEventSeverity(StrEnum):
    """Severity retained for a source-linked Trust event."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrustEventType(StrEnum):
    """Trusted source categories for future Trust evidence adapters."""

    TASK_OUTCOME = "TASK_OUTCOME"
    REVIEW_OUTCOME = "REVIEW_OUTCOME"
    QA_OUTCOME = "QA_OUTCOME"
    SECURITY_OUTCOME = "SECURITY_OUTCOME"
    PERMISSION_DECISION = "PERMISSION_DECISION"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    INCIDENT = "INCIDENT"
    AUDIT_GAP = "AUDIT_GAP"
