"""Strict bounded authentication contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class OIDCVerificationError(RuntimeError):
    """Content-free token validation failure."""

    def __init__(self) -> None:
        super().__init__("OIDC token is invalid")


class _AuthModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)


class OIDCConfiguration(_AuthModel):
    issuer: HttpUrl
    audience: str = Field(min_length=1, max_length=255)
    jwks_cache_seconds: float = Field(default=300.0, gt=0.0, le=3_600.0, allow_inf_nan=False)
    max_token_bytes: int = Field(default=16_384, ge=1_024, le=65_536)
    max_jwks_keys: int = Field(default=16, ge=1, le=64)


class OIDCClaims(_AuthModel):
    issuer: str = Field(min_length=1, max_length=2_048)
    subject: str = Field(min_length=1, max_length=255)
    audience: str = Field(min_length=1, max_length=255)
    issued_at: datetime
    expires_at: datetime
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
