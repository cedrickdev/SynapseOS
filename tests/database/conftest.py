"""Real-PostgreSQL fixtures for Phase 2 database tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session

from alembic import command
from core.config import get_settings
from infrastructure.database.append_only import register_append_only_guard

register_append_only_guard()

TEST_DATABASE_PREFIX = "synapseos_test_"


def _database_urls(database_name: str) -> tuple[str, str]:
    settings = get_settings()
    admin_url = URL.create(
        "postgresql",
        username=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.test_postgres_host,
        port=settings.test_postgres_port,
        database="postgres",
    ).render_as_string(hide_password=False)
    database_url = URL.create(
        "postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.test_postgres_host,
        port=settings.test_postgres_port,
        database=database_name,
    ).render_as_string(hide_password=False)
    return admin_url, database_url


def _create_test_database() -> tuple[str, str, str]:
    database_name = f"{TEST_DATABASE_PREFIX}{uuid.uuid4().hex}"
    admin_url, database_url = _database_urls(database_name)
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except psycopg.Error as error:
        pytest.fail(
            "PostgreSQL is required for Phase 2 tests. Start it with "
            f"`docker compose up -d db`. Connection failed: {error.__class__.__name__}"
        )
    return database_name, admin_url, database_url


def _drop_test_database(database_name: str, admin_url: str) -> None:
    if not database_name.startswith(TEST_DATABASE_PREFIX):
        raise RuntimeError(f"Refusing to drop unsafe database name: {database_name}")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
        )


@pytest.fixture(scope="session")
def migration_database_url() -> Iterator[str]:
    database_name, admin_url, database_url = _create_test_database()
    try:
        yield database_url
    finally:
        _drop_test_database(database_name, admin_url)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    database_name, admin_url, database_url = _create_test_database()
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    try:
        yield database_url
    finally:
        _drop_test_database(database_name, admin_url)


@pytest.fixture(scope="session")
def database_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(database_engine: Engine) -> Iterator[Session]:
    with database_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
