"""Central immutable audit-log interface."""

from infrastructure.audit.service import AuditLogService, AuditRecord

__all__ = ["AuditLogService", "AuditRecord"]
