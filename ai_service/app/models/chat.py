"""Chat user reference, conversation, and message models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import AgentExecution
    from app.models.approval import PendingApproval
    from app.models.checkpoint import WorkflowCheckpointMetadata


class ChatUserReference(Base):
    """Reference tracking a banking user in the AI service."""

    __tablename__ = "chat_user_reference"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    banking_user_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    role_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name_masked: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="user_reference", cascade="all, delete-orphan"
    )


class Conversation(Base):
    """User conversation session."""

    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_user_reference.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user_reference: Mapped[ChatUserReference] = relationship(
        "ChatUserReference", back_populates="conversations"
    )
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage", back_populates="conversation", cascade="all, delete-orphan"
    )
    executions: Mapped[list[AgentExecution]] = relationship(
        "AgentExecution", back_populates="conversation", cascade="all, delete-orphan"
    )
    pending_approvals: Mapped[list[PendingApproval]] = relationship(
        "PendingApproval", back_populates="conversation", cascade="all, delete-orphan"
    )
    checkpoints: Mapped[list[WorkflowCheckpointMetadata]] = relationship(
        "WorkflowCheckpointMetadata",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base):
    """Individual chat turn / message in a conversation."""

    __tablename__ = "chat_message"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user/assistant/tool/system
    content_masked: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )
