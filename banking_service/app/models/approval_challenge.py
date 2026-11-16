"""Approval challenge model for pre-auth tokens."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ApprovalChallenge(Base):
    """Pre-authentication challenge for sensitive customer operations."""

    __tablename__ = "approval_challenge"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # e.g. BENEFICIARY_CREATE, BENEFICIARY_MODIFY
    payload_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # SHA-256 of the payload being approved
    pin_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # User's PIN hash snapshot at challenge issuance
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False
    )  # PENDING, VERIFIED, CONSUMED, EXPIRED, LOCKED
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approval_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # SHA-256 hash of the issued approval token
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship("User")
