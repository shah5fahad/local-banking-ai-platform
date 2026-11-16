"""PendingApproval model for HITL workflows."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat import Conversation


class ApprovalStatus(StrEnum):
    """Lifecycle statuses for HITL approval requests."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTHENTICATED = "AUTHENTICATED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class WorkflowType(StrEnum):
    """Supported human-in-the-loop workflows."""

    BENEFICIARY = "BENEFICIARY"
    TRANSFER = "TRANSFER"
    LOAN = "LOAN"
    CARD_PAYMENT = "CARD_PAYMENT"


class RiskLevel(StrEnum):
    """Risk classification for actions."""

    READ = "READ"
    WRITE_LOW = "WRITE_LOW"
    SENSITIVE = "SENSITIVE"
    FINANCIAL = "FINANCIAL"
    HIGH = "HIGH"


DEFAULT_APPROVAL_TTL_SECONDS: dict[str, int] = {
    WorkflowType.TRANSFER.value: 300,       # 5 minutes
    WorkflowType.CARD_PAYMENT.value: 300,   # 5 minutes
    WorkflowType.BENEFICIARY.value: 600,    # 10 minutes
    WorkflowType.LOAN.value: 1800,          # 30 minutes
}


class PendingApproval(Base):
    """Pending action approval requiring human confirmation or MFA."""

    __tablename__ = "pending_approval"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workflow_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # BENEFICIARY / TRANSFER / LOAN / CARD_PAYMENT
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    summary_masked_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    banking_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=ApprovalStatus.PENDING.value, nullable=False
    )  # PENDING/CONFIRMED/REJECTED/AUTH_REQUIRED/AUTHENTICATED/EXECUTED/EXPIRED/CANCELLED/SUPERSEDED
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="pending_approvals"
    )

    __table_args__ = (
        Index("ix_pending_approval_status_expires_at", "status", "expires_at"),
    )

    @property
    def is_expired(self) -> bool:
        """Return True if current time has passed expires_at."""
        if not self.expires_at:
            return False
        now = datetime.now(UTC)
        if self.expires_at.tzinfo is None:
            return self.expires_at < now.replace(tzinfo=None)
        return self.expires_at < now

    @property
    def summary_masked(self) -> dict[str, Any]:
        """Safely parse summary_masked_json into a dict."""
        try:
            return json.loads(self.summary_masked_json)
        except Exception:
            return {"raw": self.summary_masked_json}
