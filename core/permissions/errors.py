"""Sanitized errors for the Phase 7 permission boundary."""

from __future__ import annotations


class PermissionError(Exception):
    """Base permission failure carrying only a constant-safe message."""


class PermissionInputError(PermissionError):
    """Raised when an authorization request cannot be accepted safely."""


class PermissionPolicyError(PermissionError):
    """Raised when policy authority cannot be evaluated safely."""


class PermissionAuditError(PermissionError):
    """Raised when mandatory permission auditing cannot be completed."""
