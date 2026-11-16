"""Repository for conversation persistence, message history, and agent execution tracking."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.agent import AgentExecution
from app.models.chat import ChatMessage, ChatUserReference, Conversation

logger = logging.getLogger(__name__)


class ConversationRepository:
    """Repository handling database queries for AI conversations, messages, and executions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_user_ref(
        self,
        banking_user_id: str,
        role_snapshot: str,
        display_name_masked: str,
    ) -> ChatUserReference:
        """Get or create ChatUserReference tracking the banking user."""
        stmt = select(ChatUserReference).where(
            ChatUserReference.banking_user_id == banking_user_id
        )
        user_ref = self.session.execute(stmt).scalar_one_or_none()

        if user_ref is None:
            user_ref = ChatUserReference(
                banking_user_id=banking_user_id,
                role_snapshot=role_snapshot,
                display_name_masked=display_name_masked,
            )
            self.session.add(user_ref)
            self.session.flush()
            self.session.refresh(user_ref)
        else:
            changed = False
            if user_ref.role_snapshot != role_snapshot:
                user_ref.role_snapshot = role_snapshot
                changed = True
            if user_ref.display_name_masked != display_name_masked:
                user_ref.display_name_masked = display_name_masked
                changed = True
            if changed:
                self.session.flush()
                self.session.refresh(user_ref)

        return user_ref

    def create_conversation(
        self,
        user_ref_id: str,
        title: str | None = None,
    ) -> Conversation:
        """Create a new conversation session."""
        conv = Conversation(
            user_ref_id=user_ref_id,
            title=title,
            status="ACTIVE",
        )
        self.session.add(conv)
        self.session.flush()
        self.session.refresh(conv)
        return conv

    def get_conversation(
        self,
        conversation_id: str,
        user_ref_id: str,
    ) -> Conversation | None:
        """Fetch conversation by ID verifying user ownership and non-deleted status."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_ref_id == user_ref_id,
                Conversation.deleted_at.is_(None),
            )
            .options(selectinload(Conversation.messages))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_conversations(
        self,
        user_ref_id: str,
        page: int = 1,
        page_size: int = 20,
        q: str | None = None,
    ) -> tuple[list[Conversation], int]:
        """List active conversations for a user with pagination and optional search."""
        count_stmt = select(func.count(Conversation.id)).where(
            Conversation.user_ref_id == user_ref_id,
            Conversation.deleted_at.is_(None),
        )
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_ref_id == user_ref_id,
                Conversation.deleted_at.is_(None),
            )
            .options(selectinload(Conversation.messages))
        )

        if q and q.strip():
            pattern = f"%{q.strip()}%"
            count_stmt = count_stmt.where(Conversation.title.ilike(pattern))
            stmt = stmt.where(Conversation.title.ilike(pattern))

        total = self.session.execute(count_stmt).scalar_one() or 0

        offset = max(0, (page - 1) * page_size)
        stmt = stmt.order_by(Conversation.updated_at.desc()).offset(offset).limit(page_size)
        items = list(self.session.execute(stmt).scalars().all())
        return items, total

    def update_conversation_title(
        self,
        conversation_id: str,
        user_ref_id: str,
        title: str,
    ) -> Conversation | None:
        """Update conversation title."""
        conv = self.get_conversation(conversation_id, user_ref_id)
        if conv is None:
            return None

        conv.title = title
        conv.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        self.session.refresh(conv)
        return conv

    def soft_delete_conversation(
        self,
        conversation_id: str,
        user_ref_id: str,
    ) -> bool:
        """Soft delete a conversation by setting deleted_at and status."""
        conv = self.get_conversation(conversation_id, user_ref_id)
        if conv is None:
            return False

        conv.deleted_at = datetime.now(timezone.utc)
        conv.status = "DELETED"
        self.session.flush()
        return True

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content_masked: str,
        citations_json: str | None = None,
    ) -> ChatMessage:
        """Append a message to the conversation and touch updated_at."""
        msg = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content_masked=content_masked,
            citations_json=citations_json,
        )
        self.session.add(msg)

        now = datetime.now(timezone.utc)
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=now)
        )
        self.session.execute(stmt)

        self.session.flush()
        self.session.refresh(msg)
        return msg

    def list_messages(
        self,
        conversation_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> list[ChatMessage]:
        """Fetch messages for a conversation ordered chronologically."""
        offset = max(0, (page - 1) * page_size)
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
        return list(self.session.execute(stmt).scalars().all())

    def log_execution(
        self,
        conversation_id: str,
        message_id: str | None,
        node: str,
        route: str | None,
        tool_name: str | None,
        tool_args_masked: str | None,
        status: str,
        latency_ms: int | None,
        error_code: str | None,
        request_id: str | None,
        token_usage: int | None = None,
    ) -> AgentExecution:
        """Record an agent execution trace entry."""
        execution = AgentExecution(
            conversation_id=conversation_id,
            message_id=message_id,
            node=node,
            route=route,
            tool_name=tool_name,
            tool_args_masked=tool_args_masked,
            status=status,
            latency_ms=latency_ms,
            token_usage=token_usage,
            error_code=error_code,
            request_id=request_id,
        )
        self.session.add(execution)
        self.session.flush()
        self.session.refresh(execution)
        return execution
