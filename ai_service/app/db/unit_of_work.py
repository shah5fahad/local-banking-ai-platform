"""Unit of Work pattern for the AI service.

The UnitOfWork wraps a single SQLAlchemy session / database transaction.
It commits on clean exit and rolls back on any exception, ensuring atomic writes.
"""
from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from app.db.engine import get_session_factory


class UnitOfWork:
    """Context manager that provides an atomic database transaction."""

    def __init__(self) -> None:
        self._factory = get_session_factory()
        self.session: Session

    def __enter__(self) -> "UnitOfWork":
        self.session = self._factory()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()

    def commit(self) -> None:
        """Explicit commit."""
        self.session.commit()

    def rollback(self) -> None:
        """Explicit rollback without raising."""
        self.session.rollback()
