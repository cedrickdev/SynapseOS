"""Fail-closed validated settings for the production composition root."""

from __future__ import annotations

import math
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr

from core.config import Settings
from core.production.errors import ProductionConfigurationError

_MAX_NETWORK_RESPONSE_BYTES = 16_777_216
_MAX_TIMEOUT_SECONDS = 3_600.0
_PLACEHOLDER_MARKERS = (
    "change-me",
    "example",
    "placeholder",
    "replace-me",
    "replace-with",
)


class ProductionSettings(BaseModel):
    """Immutable configuration accepted by production infrastructure builders."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    database_url: str
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    ollama_max_response_bytes: int
    github_base_url: str
    github_max_response_bytes: int
    github_service_token: SecretStr | None
    github_app_id: int | None
    github_installation_id: int | None
    github_app_private_key: SecretStr | None
    dashboard_service_token: SecretStr
    workspace_base_root: Path
    git_executable: Path
    engineering_v1_timeout_seconds: float


def validate_production_settings(settings: Settings) -> ProductionSettings:
    """Return canonical production settings or one content-free failure."""
    try:
        if type(settings) is not Settings or settings.app_env != "production":
            raise ValueError
        _validate_database_url(settings.database_url)
        _validate_provider_url(settings.ollama_base_url, schemes=frozenset({"http", "https"}))
        _validate_provider_url(settings.github_base_url, schemes=frozenset({"https"}))
        if not settings.ollama_model.strip():
            raise ValueError
        _validate_timeout(settings.ollama_timeout_seconds)
        _validate_timeout(settings.engineering_v1_timeout_seconds)
        _validate_response_limit(settings.ollama_max_response_bytes)
        _validate_response_limit(settings.github_max_response_bytes)
        if not settings.workspace_base_root.is_absolute():
            raise ValueError
        if not settings.git_executable.is_absolute():
            raise ValueError
        _validate_github_authentication(settings)
        dashboard_service_token = _secret_value(settings.dashboard_service_token)
        if dashboard_service_token is None or _is_placeholder(dashboard_service_token):
            raise ValueError
        return ProductionSettings(
            database_url=settings.database_url,
            ollama_base_url=settings.ollama_base_url.rstrip("/"),
            ollama_model=settings.ollama_model.strip(),
            ollama_timeout_seconds=float(settings.ollama_timeout_seconds),
            ollama_max_response_bytes=settings.ollama_max_response_bytes,
            github_base_url=settings.github_base_url.rstrip("/"),
            github_max_response_bytes=settings.github_max_response_bytes,
            github_service_token=settings.github_service_token,
            github_app_id=settings.github_app_id,
            github_installation_id=settings.github_installation_id,
            github_app_private_key=settings.github_app_private_key,
            dashboard_service_token=SecretStr(dashboard_service_token),
            workspace_base_root=settings.workspace_base_root,
            git_executable=settings.git_executable,
            engineering_v1_timeout_seconds=float(settings.engineering_v1_timeout_seconds),
        )
    except (AttributeError, TypeError, ValueError):
        raise ProductionConfigurationError() from None


def _validate_database_url(value: str) -> None:
    parsed = urlsplit(value)
    database_name = parsed.path.removeprefix("/")
    if (
        parsed.scheme != "postgresql+psycopg"
        or not parsed.hostname
        or not parsed.username
        or not parsed.password
        or not database_name
        or parsed.query
        or parsed.fragment
        or _is_placeholder(parsed.password)
        or (parsed.username.casefold(), parsed.password.casefold()) == ("synapseos", "synapseos")
    ):
        raise ValueError


def _validate_provider_url(value: str, *, schemes: frozenset[str]) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError


def _validate_timeout(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 < float(value) <= _MAX_TIMEOUT_SECONDS
    ):
        raise ValueError


def _validate_response_limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= _MAX_NETWORK_RESPONSE_BYTES:
        raise ValueError


def _validate_github_authentication(settings: Settings) -> None:
    service_token = _secret_value(settings.github_service_token)
    private_key = _secret_value(settings.github_app_private_key)
    app_values = (settings.github_app_id, settings.github_installation_id, private_key)
    has_service_token = service_token is not None
    has_any_app_value = any(value is not None for value in app_values)
    has_complete_app_config = all(value is not None for value in app_values)
    if has_service_token == has_any_app_value or has_any_app_value != has_complete_app_config:
        raise ValueError
    if service_token is not None and _is_placeholder(service_token):
        raise ValueError
    if private_key is not None and _is_placeholder(private_key):
        raise ValueError
    if settings.github_app_id is not None and settings.github_app_id <= 0:
        raise ValueError
    if settings.github_installation_id is not None and settings.github_installation_id <= 0:
        raise ValueError


def _secret_value(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    revealed = value.get_secret_value().strip()
    return revealed or None


def _is_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)
