"""Shared domain enums persisted by the Phase 2 data model."""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    """Canonical capabilities shared by agents, tools, and persistence."""

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    GIT_READ = "git.read"
    GIT_WRITE = "git.write"
    SHELL_EXECUTE = "shell.execute"
    TESTS_EXECUTE = "tests.execute"
    NETWORK_ACCESS = "network.access"
    DATABASE_READ = "database.read"
    DATABASE_WRITE = "database.write"
    DEPLOYMENT_STAGING = "deployment.staging"
    DEPLOYMENT_PRODUCTION = "deployment.production"


class ToolRiskLevel(StrEnum):
    """Risk classification shared by tool definitions and permission policy."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgentSeniority(StrEnum):
    TRAINEE = "TRAINEE"
    JUNIOR = "JUNIOR"
    ENGINEER = "ENGINEER"
    SENIOR = "SENIOR"
    STAFF = "STAFF"
    PRINCIPAL = "PRINCIPAL"


class AgentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    WORKING = "WORKING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    OFFLINE = "OFFLINE"


class ProjectStatus(StrEnum):
    INTAKE = "INTAKE"
    DISCOVERY = "DISCOVERY"
    PLANNING = "PLANNING"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    STAGING = "STAGING"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_REVIEW = "WAITING_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    WAITING_QA = "WAITING_QA"
    WAITING_SECURITY = "WAITING_SECURITY"
    BLOCKED = "BLOCKED"
    WAITING_HUMAN = "WAITING_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgentRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class DecisionOutcome(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ToolCallStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMED_OUT = "TIMED_OUT"


class AgentScoreType(StrEnum):
    CONFIDENCE = "CONFIDENCE"
    RELIABILITY = "RELIABILITY"
    EXPERTISE = "EXPERTISE"
    CODE_QUALITY = "CODE_QUALITY"
    SECURITY = "SECURITY"
    COLLABORATION = "COLLABORATION"
    CUSTOMER_SATISFACTION = "CUSTOMER_SATISFACTION"


class ScoreSourceType(StrEnum):
    REVIEW = "REVIEW"
    QA = "QA"
    SECURITY = "SECURITY"
    FEEDBACK = "FEEDBACK"
    SYSTEM = "SYSTEM"


class AuditActorType(StrEnum):
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    WORKER = "WORKER"
    TOOL = "TOOL"
    WEBHOOK = "WEBHOOK"


class AuditResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
