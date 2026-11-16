"""SQLAlchemy ORM model for Audit Logs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Immutable, append-only audit trail."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(
        String(32), default="USER", nullable=False
    )  # USER, ADMIN, SERVICE, SYSTEM
    service: Mapped[str] = mapped_column(String(32), default="banking", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), default="SUCCESS", nullable=False)  # SUCCESS, FAILURE
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_logs_actor_ts", "actor_user_id", "ts"),
        Index("ix_audit_logs_action_ts", "action", "ts"),
    )
