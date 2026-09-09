"""Memory V1 enums."""

from enum import StrEnum


class MemoryScope(StrEnum):
    AGENT = "AGENT"
    PROJECT = "PROJECT"
    COMPANY = "COMPANY"


class MemoryType(StrEnum):
    GENERAL = "GENERAL"
    DECISION = "DECISION"
    FAILURE = "FAILURE"
