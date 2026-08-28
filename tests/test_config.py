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


def test_write_settings_have_finite_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.write_max_input_bytes == 1_048_576
    assert settings.write_max_existing_bytes == 4_194_304
    assert settings.write_max_patch_operations == 128
    assert settings.write_max_patch_text_bytes == 262_144
    assert settings.write_max_diff_bytes == 262_144
    assert settings.write_timeout_seconds == 10.0


@pytest.mark.parametrize(
    "environment_key",
    [
        "WRITE_MAX_INPUT_BYTES",
        "WRITE_MAX_EXISTING_BYTES",
        "WRITE_MAX_PATCH_OPERATIONS",
        "WRITE_MAX_PATCH_TEXT_BYTES",
        "WRITE_MAX_DIFF_BYTES",
        "WRITE_TIMEOUT_SECONDS",
    ],
)
def test_write_settings_reject_non_positive_limits(
    environment_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(environment_key, "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_command_settings_have_finite_bounded_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.command_timeout_seconds == 30.0
    assert settings.command_stdout_max_bytes == 98_304
    assert settings.command_stderr_max_bytes == 32_768
    assert settings.command_marker_max_bytes == 262_144
    assert settings.command_read_chunk_bytes == 65_536
    assert settings.command_termination_grace_seconds == 1.0


def test_command_settings_are_overridden_by_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMMAND_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("COMMAND_STDOUT_MAX_BYTES", "4096")
    monkeypatch.setenv("COMMAND_STDERR_MAX_BYTES", "2048")
    monkeypatch.setenv("COMMAND_MARKER_MAX_BYTES", "8192")
    monkeypatch.setenv("COMMAND_READ_CHUNK_BYTES", "1024")
    monkeypatch.setenv("COMMAND_TERMINATION_GRACE_SECONDS", "0.5")

    settings = Settings(_env_file=None)

    assert settings.command_timeout_seconds == 12.5
    assert settings.command_stdout_max_bytes == 4_096
    assert settings.command_stderr_max_bytes == 2_048
    assert settings.command_marker_max_bytes == 8_192
    assert settings.command_read_chunk_bytes == 1_024
    assert settings.command_termination_grace_seconds == 0.5


def test_command_settings_reject_an_oversized_combined_stream_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMMAND_STDOUT_MAX_BYTES", "98305")
    monkeypatch.setenv("COMMAND_STDERR_MAX_BYTES", "32768")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("environment_key", "value"),
    [
        ("COMMAND_TIMEOUT_SECONDS", "0"),
        ("COMMAND_TIMEOUT_SECONDS", "31"),
        ("COMMAND_TIMEOUT_SECONDS", "inf"),
        ("COMMAND_STDOUT_MAX_BYTES", "1048577"),
        ("COMMAND_STDERR_MAX_BYTES", "0"),
        ("COMMAND_MARKER_MAX_BYTES", "1048577"),
        ("COMMAND_READ_CHUNK_BYTES", "65537"),
        ("COMMAND_TERMINATION_GRACE_SECONDS", "5.1"),
    ],
)
def test_command_settings_reject_unbounded_values(
    environment_key: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(environment_key, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
