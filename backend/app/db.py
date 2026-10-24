"""Database engine and session plumbing.

SQLite, accessed synchronously. Route handlers are plain ``def`` functions, which FastAPI
runs in its threadpool — that avoids both the aiosqlite dependency and the whole class of
bugs where a blocking call lands on the event loop.

The pragmas below are not optional decoration:

* ``foreign_keys`` is **per connection** in SQLite and off by default. Without it every
  ``ON DELETE CASCADE`` in the schema silently does nothing and deleting a match leaves
  its players, rounds and events behind. A test asserts cascades actually fire.
* ``journal_mode=WAL`` lets the parser subprocess write progress while the API reads.
* ``busy_timeout`` makes that concurrency wait rather than raise "database is locked".
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Build an engine with the required SQLite pragmas attached."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = create_engine(
        settings.sqlalchemy_url,
        # The parse worker is a separate process, but the API's own threadpool shares
        # connections across threads.
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def get_engine() -> Engine:
    """The process-wide engine, created on first use."""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_db_engine()
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None  # noqa: S101 - set by get_engine
    return _session_factory


def reset_engine() -> None:
    """Drop the cached engine. Used by tests that point at a different database."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transactional session: commits on success, rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
