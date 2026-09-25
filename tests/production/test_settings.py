"""Tests for fail-closed production configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from core.config import Settings
from core.production import (
    ProductionConfigurationError,
    ProductionSettings,
    validate_production_settings,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://synapse:strong-password@db:5432/synapseos",
        "ollama_base_url": "http://ollama:11434",
        "ollama_model": "qwen3:8b",
        "ollama_timeout_seconds": 60.0,
        "ollama_max_response_bytes": 1_048_576,
        "github_base_url": "https://api.github.com",
        "github_max_response_bytes": 1_048_576,
        "github_service_token": SecretStr("github-service-token-value"),
        "github_app_id": None,
        "github_installation_id": None,
        "github_app_private_key": None,
        "workspace_base_root": Path("/var/lib/synapseos/workspaces"),
        "git_executable": Path("/usr/bin/git"),
        "engineering_v1_timeout_seconds": 900.0,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "database_url",
            "postgresql+psycopg://synapse:change-me-in-your-local-env@db:5432/synapseos",
        ),
        ("github_service_token", SecretStr("replace-with-a-real-token")),
    ],
)
def test_production_settings_reject_placeholder_credentials(
    field: str,
    value: object,
) -> None:
    settings = _settings(**{field: value})

    with pytest.raises(ProductionConfigurationError) as captured:
        validate_production_settings(settings)

    assert "change-me-in-your-local-env" not in str(captured.value)
    assert "replace-with-a-real-token" not in str(captured.value)


def test_production_settings_require_exactly_one_github_auth_strategy() -> None:
    with pytest.raises(ProductionConfigurationError):
        validate_production_settings(_settings(github_service_token=None))

    with pytest.raises(ProductionConfigurationError):
        validate_production_settings(
            _settings(
                github_app_id=123,
                github_installation_id=456,
                github_app_private_key=SecretStr("private-key-value"),
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite:///synapseos.db"),
        ("ollama_base_url", "http://user:password@ollama:11434"),
        ("github_base_url", "https://user:password@api.github.com"),
        ("ollama_model", "   "),
        ("ollama_timeout_seconds", 3_601.0),
        ("ollama_max_response_bytes", 16_777_217),
        ("github_max_response_bytes", 16_777_217),
        ("workspace_base_root", Path("relative/workspaces")),
        ("git_executable", Path("git")),
    ],
)
def test_production_settings_reject_unsafe_or_unbounded_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ProductionConfigurationError):
        validate_production_settings(_settings(**{field: value}))


def test_raw_settings_reject_unbounded_engineering_timeout() -> None:
    with pytest.raises(ValidationError):
        _settings(engineering_v1_timeout_seconds=3_601.0)


def test_production_settings_accept_service_token_authentication() -> None:
    validated = validate_production_settings(_settings())

    assert isinstance(validated, ProductionSettings)
    assert validated.github_service_token is not None
    assert validated.github_app_id is None
    assert validated.database_url.startswith("postgresql+psycopg://")


def test_production_settings_accept_complete_github_app_authentication() -> None:
    validated = validate_production_settings(
        _settings(
            github_service_token=None,
            github_app_id=123,
            github_installation_id=456,
            github_app_private_key=SecretStr("private-key-value"),
        )
    )

    assert validated.github_service_token is None
    assert validated.github_app_id == 123
    assert validated.github_installation_id == 456
    assert validated.github_app_private_key is not None


def test_production_settings_are_immutable() -> None:
    validated = validate_production_settings(_settings())
    field_name = "ollama_model"

    with pytest.raises(ValidationError):
        setattr(validated, field_name, "another-model")


def test_production_validation_rejects_non_production_environment() -> None:
    with pytest.raises(ProductionConfigurationError):
        validate_production_settings(_settings(app_env="development"))
