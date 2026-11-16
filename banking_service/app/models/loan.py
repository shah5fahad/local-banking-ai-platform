"""SQLAlchemy ORM models for Loan Offers and Applications."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class LoanOffer(Base):
    """Pre-approved or standard loan offer."""

    __tablename__ = "loan_offers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    loan_type: Mapped[str] = mapped_column(String(32), nullable=False)  # PERSONAL, HOME, AUTO
    max_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # basis points (e.g. 1050 = 10.50%)
    min_tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_till: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    terms: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, INACTIVE
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[Optional[User]] = relationship("User", back_populates="loan_offers")


class LoanApplication(Base):
    """Loan application submitted by user."""

    __tablename__ = "loan_applications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("loan_offers.id", ondelete="SET NULL"), nullable=True
    )
    loan_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    employment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    employer: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_income_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="SUBMITTED", nullable=False
    )  # SUBMITTED, UNDER_REVIEW, APPROVED, REJECTED
    decision_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_loan_idempotency"),
    )

    user: Mapped[User] = relationship("User", back_populates="loan_applications")
    offer: Mapped[Optional[LoanOffer]] = relationship("LoanOffer")
