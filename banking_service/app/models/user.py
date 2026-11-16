"""SQLAlchemy ORM models for Users, Roles, and Sessions."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.account import BankAccount
    from app.models.beneficiary import Beneficiary
    from app.models.transaction import BankTransaction
    from app.models.loan import LoanApplication, LoanOffer
    from app.models.credit_card import CreditCard


class UserRole(Base):
    """Association table between User and Role."""

    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class Role(Base):
    """User role model (CUSTOMER, ADMIN, AUDITOR)."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    users: Mapped[List[User]] = relationship(
        "User", secondary="user_roles", back_populates="roles"
    )

    @property
    def role(self) -> Role:
        """Alias returning self so both role.name and ur.role.name work."""
        return self


class User(Base):
    """Bank customer / user account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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

    roles: Mapped[List[Role]] = relationship(
        "Role", secondary="user_roles", back_populates="users", lazy="joined"
    )
    sessions: Mapped[List[Session]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    accounts: Mapped[List[BankAccount]] = relationship(
        "BankAccount", back_populates="user", cascade="all, delete-orphan"
    )
    beneficiaries: Mapped[List[Beneficiary]] = relationship(
        "Beneficiary", back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[List[BankTransaction]] = relationship(
        "BankTransaction", back_populates="user"
    )
    loan_applications: Mapped[List[LoanApplication]] = relationship(
        "LoanApplication", back_populates="user"
    )
    credit_cards: Mapped[List[CreditCard]] = relationship(
        "CreditCard", back_populates="user"
    )
    loan_offers: Mapped[List[LoanOffer]] = relationship(
        "LoanOffer", back_populates="user", cascade="all, delete-orphan"
    )


class Session(Base):
    """User authentication session / refresh token."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="sessions")
