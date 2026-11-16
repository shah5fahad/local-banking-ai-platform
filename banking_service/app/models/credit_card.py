"""SQLAlchemy ORM models for Credit Cards, Statements, and Payments."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.account import BankAccount
    from app.models.transaction import BankTransaction


class CreditCard(Base):
    """Credit card held by user (no PAN/CVV stored)."""

    __tablename__ = "credit_cards"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_token: Mapped[str] = mapped_column(String(128), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    network: Mapped[str] = mapped_column(String(32), default="VISA", nullable=False)  # VISA, MASTERCARD, RUPAY
    credit_limit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outstanding_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, BLOCKED, CLOSED
    card_number_encrypted: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    card_number_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    cvv_encrypted: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    cvv_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="credit_cards")
    statements: Mapped[List[CreditCardStatement]] = relationship(
        "CreditCardStatement", back_populates="card", cascade="all, delete-orphan"
    )
    payments: Mapped[List[CreditCardPayment]] = relationship(
        "CreditCardPayment", back_populates="card"
    )

    @property
    def card_number_masked(self) -> str:
        return f"XXXX-XXXX-XXXX-{self.last4}"


class CreditCardStatement(Base):
    """Monthly billing statement for a credit card."""

    __tablename__ = "credit_card_statements"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    card_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credit_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    min_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="UNPAID", nullable=False
    )  # UNPAID, PARTIALLY_PAID, PAID
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    card: Mapped[CreditCard] = relationship("CreditCard", back_populates="statements")


class CreditCardPayment(Base):
    """Credit card payment record."""

    __tablename__ = "credit_card_payments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    card_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credit_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("credit_card_statements.id", ondelete="SET NULL"), nullable=True
    )
    source_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING_APPROVAL", nullable=False
    )  # PENDING_APPROVAL, AUTHORIZED, COMPLETED, FAILED
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    card: Mapped[CreditCard] = relationship("CreditCard", back_populates="payments")
    statement: Mapped[Optional[CreditCardStatement]] = relationship("CreditCardStatement")
