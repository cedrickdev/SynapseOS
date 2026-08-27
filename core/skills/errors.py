"""Sanitized failures for skill validation, loading, and lookup."""

from __future__ import annotations

from enum import StrEnum


class SkillErrorCode(StrEnum):
    """Stable public classifications without rejected input details."""

    INVALID_INPUT = "INVALID_INPUT"
    UNSAFE_PATH = "UNSAFE_PATH"
    INVALID_METADATA = "INVALID_METADATA"
    INVALID_CONTENT = "INVALID_CONTENT"
    DUPLICATE_ID = "DUPLICATE_ID"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    UNKNOWN_SKILL = "UNKNOWN_SKILL"


class SkillError(Exception):
    """Base sanitized skill failure."""

    def __init__(self, code: SkillErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class SkillLoadError(SkillError):
    """A local skill snapshot could not be loaded safely."""


class SkillRegistryError(SkillError):
    """A registry snapshot is invalid."""
