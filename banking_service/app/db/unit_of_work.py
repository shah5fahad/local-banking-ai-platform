"""Unit of Work pattern for the Banking service.

The UnitOfWork wraps a single SQLAlchemy session / database transaction.
It commits on clean exit and rolls back on any exception, ensuring that all
repository writes within a single use-case are atomic.

Usage::

    from app.db.unit_of_work import UnitOfWork

    with UnitOfWork() as uow:
        uow.transactions.create(...)
        # commit happens automatically at __exit__
"""
from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.engine import get_session_factory

if TYPE_CHECKING:
    from app.repositories.audit_repository import AuditRepository
    from app.repositories.card_repository import CardRepository
    from app.repositories.loan_repository import LoanRepository
    from app.repositories.transaction_repository import TransactionRepository


class UnitOfWork:
    """Context manager that provides an atomic database transaction."""

    def __init__(self) -> None:
        self._factory = get_session_factory()
        # Populated on __enter__
        self.session: Session

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Explicit helpers
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """Explicit commit."""
        self.session.commit()

    def rollback(self) -> None:
        """Explicit rollback without raising."""
        self.session.rollback()

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    @property
    def transactions(self) -> "TransactionRepository":
        from app.repositories.transaction_repository import TransactionRepository
        return TransactionRepository(self.session)

    @property
    def loans(self) -> "LoanRepository":
        from app.repositories.loan_repository import LoanRepository
        return LoanRepository(self.session)

    @property
    def cards(self) -> "CardRepository":
        from app.repositories.card_repository import CardRepository
        return CardRepository(self.session)

    @property
    def audit(self) -> "AuditRepository":
        from app.repositories.audit_repository import AuditRepository
        return AuditRepository(self.session)
