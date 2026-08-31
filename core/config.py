"""Application configuration for SynapseOS.

Settings are read from environment variables (and an optional local ``.env``
file). No secrets are hard-coded; see ``.env.example`` for the expected keys.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    postgres_user: str = "synapseos"
    postgres_password: str = "synapseos"
    postgres_db: str = "synapseos"
    test_postgres_host: str = "localhost"
    test_postgres_port: int = 55432
    database_url: str = "postgresql+psycopg://synapseos:synapseos@localhost:55432/synapseos"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = Field(default=60.0, gt=0)
    ollama_max_response_bytes: int = Field(default=10_485_760, gt=0)
    workspace_base_root: Path = Path(".synapseos/workspaces")
    workspace_git_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        le=3_600,
        allow_inf_nan=False,
    )
    workspace_git_output_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    workspace_max_entries: int = Field(default=100_000, ge=1, le=1_000_000)
    workspace_max_total_bytes: int = Field(
        default=1_073_741_824,
        ge=1,
        le=1_099_511_627_776,
    )
    workspace_max_depth: int = Field(default=64, ge=1, le=256)
    workspace_local_import_roots: Annotated[tuple[Path, ...], Field(max_length=32)] = ()
    workspace_remote_hosts: Annotated[tuple[str, ...], Field(max_length=32)] = ()


def get_settings() -> Settings:
    """Return application settings loaded from the environment."""
    return Settings()
