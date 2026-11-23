"""SQLAlchemy database engine, session factory, and declarative base."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base declarative class for all PostgreSQL models."""


def build_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine with connection pre-ping enabled."""
    return create_engine(database_url, pool_pre_ping=True, future=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured SQLAlchemy sessionmaker."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Yield a transactional SQLAlchemy session."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
