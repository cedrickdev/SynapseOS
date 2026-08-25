"""Application configuration for SynapseOS.

Settings are read from environment variables (and an optional local ``.env``
file). No secrets are hard-coded; see ``.env.example`` for the expected keys.
"""

from __future__ import annotations

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


def get_settings() -> Settings:
    """Return application settings loaded from the environment."""
    return Settings()
