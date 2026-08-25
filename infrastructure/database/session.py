"""Database engine, sessions, and persistence guards for SynapseOS."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings
from infrastructure.database.append_only import register_append_only_guard

register_append_only_guard()


def create_database_engine() -> Engine:
    """Create the SQLAlchemy engine from application settings.

    The engine connects lazily: importing this module does not open a
    connection, so it is safe to import without a running database.
    """
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


engine: Engine = create_database_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_session() -> Iterator[Session]:
    """Yield a database session and ensure it is closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
