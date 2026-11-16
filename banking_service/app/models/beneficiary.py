"""SQLAlchemy ORM model for Beneficiaries."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Beneficiary(Base):
    """Saved beneficiary for funds transfer."""

    __tablename__ = "beneficiaries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    account_number_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    account_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(128), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False
    )  # PENDING, VERIFIED, FAILED
    approval_status: Mapped[str] = mapped_column(
        String(32), default="VERIFIED", nullable=False
    )  # PENDING, VERIFIED, REJECTED
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
        UniqueConstraint("user_id", "account_hash", "ifsc", name="uq_user_beneficiary_account"),
    )

    user: Mapped[User] = relationship("User", back_populates="beneficiaries")

    @property
    def account_number_masked(self) -> str:
        return f"XXXXXX{self.last4}"

