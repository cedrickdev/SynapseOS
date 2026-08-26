"""Provider-neutral values exchanged with language model providers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMRole(StrEnum):
    """Roles supported by the provider-neutral chat contract."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


NonEmptyText = Annotated[str, Field(min_length=1)]
TokenCount = Annotated[int, Field(ge=0)]


def _freeze(value: Any) -> Any:
    """Recursively detach and freeze JSON-like metadata."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("metadata keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("metadata values must be finite JSON-compatible values")


class LLMMessage(_ImmutableModel):
    """One ordered chat message."""

    role: LLMRole
    content: NonEmptyText

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value


class LLMRequest(_ImmutableModel):
    """Provider-independent generation request."""

    messages: Annotated[tuple[LLMMessage, ...], Field(min_length=1)]
    system_prompt: NonEmptyText | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0, allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(gt=0, le=131_072)] = 2048
    metadata: Mapping[str, Any] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("system_prompt")
    @classmethod
    def reject_blank_system_prompt(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("system prompt must not be blank")
        return value

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], _freeze(value))


class LLMUsage(_ImmutableModel):
    """Token counters reported by a provider when available."""

    prompt_tokens: TokenCount | None = None
    completion_tokens: TokenCount | None = None
    total_tokens: TokenCount | None = None


class LLMModelMetadata(_ImmutableModel):
    """Safe model identity and sanitized provider details."""

    provider: NonEmptyText
    model: NonEmptyText
    details: Mapping[str, Any] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("details", mode="after")
    @classmethod
    def freeze_details(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], _freeze(value))


class LLMResponse(_ImmutableModel):
    """Provider-independent generation response."""

    content: str
    finish_reason: str | None = None
    usage: LLMUsage | None = None
    model: LLMModelMetadata
