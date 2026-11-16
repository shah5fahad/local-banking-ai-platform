"""Alembic environment configuration for the Banking service.

Key behaviours:
- Database URL read from BankingSettings (BANKING_DATABASE_URL env var).
- SQLite pragmas applied before every migration run.
- render_as_batch=True to support SQLite ALTER TABLE operations.
- All models must be imported here so autogenerate detects table changes.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, event, pool, text

# Add the banking_service root to sys.path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Import all models so Alembic sees their table definitions.
# ---------------------------------------------------------------------------
import app.models  # noqa: F401 - registers all models with metadata

# ---------------------------------------------------------------------------
# Alembic Config
# ---------------------------------------------------------------------------

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_url() -> str:
    return get_settings().database_url


def _apply_sqlite_pragmas(dbapi_conn: object, _record: object) -> None:
    cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


# ---------------------------------------------------------------------------
# Migration modes
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations without an active DB connection (SQL script output)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live DB connection."""
    url = _get_url()

    # Override url in the ini section so engine_from_config picks it up
    configuration = dict(config.get_section(config.config_ini_section) or {})
    configuration["sqlalchemy.url"] = url

    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
        connect_args=(
            {"check_same_thread": False} if url.startswith("sqlite") else {}
        ),
    )

    if url.startswith("sqlite"):
        event.listen(connectable, "connect", _apply_sqlite_pragmas)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # Required for SQLite ALTER TABLE
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
