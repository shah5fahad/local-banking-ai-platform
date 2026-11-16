"""SQLAlchemy ORM models for Transactions and Transfer Authorizations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.account import BankAccount
    from app.models.beneficiary import Beneficiary


class BankTransaction(Base):
    """Bank ledger transaction record."""

    __tablename__ = "bank_transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True
    )
    beneficiary_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("beneficiaries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(
        String(32), default="TRANSFER", nullable=False
    )  # TRANSFER, CARD_PAYMENT, CREDIT, DEBIT
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING_APPROVAL", nullable=False
    )  # PENDING_APPROVAL, AUTHORIZED, PROCESSING, COMPLETED, FAILED, CANCELLED, EXPIRED
    remark: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="IMPS", nullable=False)
    summary_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_txn_idempotency"),
        Index("ix_bank_transactions_user_created", "user_id", "created_at"),
        Index("ix_bank_transactions_user_status", "user_id", "status"),
    )

    user: Mapped[User] = relationship("User", back_populates="transactions")
    authorization: Mapped[Optional[TransferAuthorization]] = relationship(
        "TransferAuthorization", back_populates="transaction", uselist=False
    )


class TransferAuthorization(Base):
    """Transfer challenge authorization record."""

    __tablename__ = "transfer_authorizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    transaction_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("bank_transactions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(16), default="PIN", nullable=False)  # PIN / OTP
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="ISSUED", nullable=False
    )  # ISSUED, VERIFIED, CONSUMED, EXPIRED, LOCKED
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    transaction: Mapped[BankTransaction] = relationship(
        "BankTransaction", back_populates="authorization"
    )
