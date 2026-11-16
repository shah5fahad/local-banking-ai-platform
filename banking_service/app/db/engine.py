"""SQLAlchemy engine factory for the Banking service.

SQLite-specific configuration applied on every new connection:
  - PRAGMA foreign_keys = ON   (enforce FK constraints)
  - PRAGMA journal_mode = WAL  (write-ahead logging for concurrency)
  - PRAGMA synchronous = NORMAL
  - PRAGMA busy_timeout = 5000 (ms to wait for a lock before error)

For PostgreSQL migration: remove the pragma listener and the
``check_same_thread`` connect arg; row-level locking replaces WAL assumptions.
"""
from __future__ import annotations

import logging

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLite connection event handler
# ---------------------------------------------------------------------------


def _apply_sqlite_pragmas(dbapi_conn: object, _connection_record: object) -> None:
    """Enable FK enforcement and WAL mode on every new SQLite connection."""
    cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_db_engine() -> Engine:
    """Create a SQLAlchemy Engine from the current settings."""
    settings = get_settings()
    connect_args: dict[str, object] = {}

    is_sqlite = settings.database_url.startswith("sqlite")
    if is_sqlite:
        # SQLite requires check_same_thread=False for multi-threaded use
        connect_args["check_same_thread"] = False

    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        # Echo SQL only in development; never in production
        echo=(settings.app_env == "development"),
    )

    if is_sqlite:
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        logger.debug("SQLite pragmas listener registered")

    return engine


# ---------------------------------------------------------------------------
# Module-level singletons (lazy-initialised)
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the singleton Engine (lazy-initialised)."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the singleton sessionmaker (lazy-initialised)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal
