"""Closed enums for Agent Genome persistence."""

from enum import StrEnum


class GenomeVersionStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED = "SUSPENDED"


class GenomeCreationSource(StrEnum):
    SYSTEM = "SYSTEM"
    HUMAN = "HUMAN"
    WORKER = "WORKER"
    MIGRATION = "MIGRATION"


class GenomeMetricWindow(StrEnum):
    RUN = "RUN"
    LAST_30_DAYS = "LAST_30_DAYS"
    ALL_TIME = "ALL_TIME"


class GenomeFailureSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
