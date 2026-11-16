"""SQLAlchemy ORM model for Bank Accounts."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class BankAccount(Base):
    """Bank account owned by a user."""

    __tablename__ = "bank_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    account_number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    account_number_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(128), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), default="SAVINGS", nullable=False)
    balance_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False
    )  # PENDING, VERIFIED, FAILED
    status: Mapped[str] = mapped_column(
        String(32), default="ACTIVE", nullable=False
    )  # ACTIVE, INACTIVE
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
        UniqueConstraint("user_id", "account_number_hash", name="uq_user_account_hash"),
    )

    user: Mapped[User] = relationship("User", back_populates="accounts")

    @property
    def account_number_masked(self) -> str:
        return f"XXXXXX{self.account_number_last4}"

