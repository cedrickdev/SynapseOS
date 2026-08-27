"""Tests for environment-driven application configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import Settings


def test_ollama_settings_have_bounded_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen3:8b"
    assert settings.ollama_timeout_seconds == 60.0
    assert settings.ollama_max_response_bytes == 10_485_760


def test_ollama_settings_are_overridden_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://models.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3:12b")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "30.5")
    monkeypatch.setenv("OLLAMA_MAX_RESPONSE_BYTES", "2048")

    settings = Settings(_env_file=None)

    assert settings.ollama_base_url == "http://models.internal:11434"
    assert settings.ollama_model == "gemma3:12b"
    assert settings.ollama_timeout_seconds == 30.5
    assert settings.ollama_max_response_bytes == 2048


@pytest.mark.parametrize(
    "environment_key",
    ["OLLAMA_TIMEOUT_SECONDS", "OLLAMA_MAX_RESPONSE_BYTES"],
)
def test_ollama_settings_reject_non_positive_limits(
    environment_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(environment_key, "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_workspace_settings_default_to_bounded_disabled_sources() -> None:
    settings = Settings(_env_file=None)

    assert settings.workspace_base_root.as_posix() == ".synapseos/workspaces"
    assert settings.workspace_git_timeout_seconds == 120.0
    assert settings.workspace_git_output_bytes == 65_536
    assert settings.workspace_max_entries == 100_000
    assert settings.workspace_max_total_bytes == 1_073_741_824
    assert settings.workspace_max_depth == 64
    assert settings.workspace_local_import_roots == ()
    assert settings.workspace_remote_hosts == ()


@pytest.mark.parametrize(
    "environment_key",
    [
        "WORKSPACE_GIT_TIMEOUT_SECONDS",
        "WORKSPACE_GIT_OUTPUT_BYTES",
        "WORKSPACE_MAX_ENTRIES",
        "WORKSPACE_MAX_TOTAL_BYTES",
        "WORKSPACE_MAX_DEPTH",
    ],
)
def test_workspace_settings_reject_non_positive_limits(
    environment_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(environment_key, "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
