"""Contract tests for shared Phase 2 ORM primitives and enums."""

from __future__ import annotations

from core.enums import (
    AgentRunStatus,
    AgentScoreType,
    AgentSeniority,
    AgentStatus,
    AuditActorType,
    AuditResult,
    DecisionOutcome,
    ProjectStatus,
    ScoreSourceType,
    TaskPriority,
    TaskStatus,
    ToolCallStatus,
)
from infrastructure.database.base import Base


def test_shared_enums_have_the_approved_persisted_values() -> None:
    assert [item.value for item in AgentSeniority] == [
        "TRAINEE",
        "JUNIOR",
        "ENGINEER",
        "SENIOR",
        "STAFF",
        "PRINCIPAL",
    ]
    assert [item.value for item in AgentStatus] == [
        "AVAILABLE",
        "ASSIGNED",
        "WORKING",
        "WAITING",
        "BLOCKED",
        "OFFLINE",
    ]
    assert [item.value for item in ProjectStatus] == [
        "INTAKE",
        "DISCOVERY",
        "PLANNING",
        "APPROVED",
        "IN_PROGRESS",
        "STAGING",
        "CLIENT_REVIEW",
        "COMPLETED",
        "ARCHIVED",
        "PAUSED",
        "CANCELLED",
    ]
    assert [item.value for item in TaskStatus] == [
        "BACKLOG",
        "READY",
        "ASSIGNED",
        "IN_PROGRESS",
        "WAITING_REVIEW",
        "CHANGES_REQUESTED",
        "WAITING_QA",
        "WAITING_SECURITY",
        "BLOCKED",
        "WAITING_HUMAN",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ]
    assert [item.value for item in TaskPriority] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert [item.value for item in AgentRunStatus] == [
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
    ]
    assert [item.value for item in DecisionOutcome] == [
        "PENDING",
        "ACCEPTED",
        "REJECTED",
        "SUPERSEDED",
    ]
    assert [item.value for item in ToolCallStatus] == [
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "DENIED",
        "TIMED_OUT",
    ]
    assert [item.value for item in AgentScoreType] == [
        "CONFIDENCE",
        "RELIABILITY",
        "EXPERTISE",
        "CODE_QUALITY",
        "SECURITY",
        "COLLABORATION",
        "CUSTOMER_SATISFACTION",
    ]
    assert [item.value for item in ScoreSourceType] == [
        "REVIEW",
        "QA",
        "SECURITY",
        "FEEDBACK",
        "SYSTEM",
    ]
    assert [item.value for item in AuditActorType] == [
        "AGENT",
        "HUMAN",
        "SYSTEM",
        "WORKER",
        "TOOL",
        "WEBHOOK",
    ]
    assert [item.value for item in AuditResult] == [
        "SUCCEEDED",
        "FAILED",
        "DENIED",
        "CANCELLED",
    ]


def test_base_uses_deterministic_constraint_naming() -> None:
    assert Base.metadata.naming_convention == {
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
