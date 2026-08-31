"""Public contracts for the Phase 7 Permission Engine."""

from core.permissions.audit import PermissionAuditRecorder
from core.permissions.engine import PermissionEngine
from core.permissions.errors import (
    PermissionAuditError,
    PermissionError,
    PermissionInputError,
    PermissionPolicyError,
)
from core.permissions.policy import PermissionPolicy
from core.permissions.types import (
    PermissionDecision,
    PermissionOutcome,
    PermissionReasonCode,
    PermissionRequest,
    PolicyRequest,
    ToolPermission,
)

__all__ = [
    "PermissionAuditError",
    "PermissionAuditRecorder",
    "PermissionDecision",
    "PermissionError",
    "PermissionEngine",
    "PermissionInputError",
    "PermissionOutcome",
    "PermissionPolicyError",
    "PermissionPolicy",
    "PermissionReasonCode",
    "PermissionRequest",
    "PolicyRequest",
    "ToolPermission",
]
