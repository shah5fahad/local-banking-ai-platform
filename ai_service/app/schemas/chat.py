"""Chat and conversation Pydantic schemas."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class CitationItem(BaseModel):
    """Citation metadata for policy or web search references."""

    ref: int
    doc_name: str
    version: str
    page: int | None = None
    section: str | None = None


class ChatRequest(BaseModel):
    """User incoming chat request."""

    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    """Response returned for chat turn."""

    conversation_id: str
    message_id: str
    response: str
    citations: list[CitationItem] | None = None
    approval_pending: bool = False
    approval_id: str | None = None


class ConversationItem(BaseModel):
    """Summary of conversation item in listing."""

    id: str
    title: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationListResponse(BaseModel):
    """Paginated conversation list response."""

    items: list[ConversationItem]
    total: int
    page: int = 1
    page_size: int = 20


class MessageItem(BaseModel):
    """Single message entry in conversation history."""

    id: str
    role: str
    content_masked: str
    citations: list[Any] | None = None
    created_at: datetime


class UpdateTitleRequest(BaseModel):
    """Payload to update conversation title."""

    title: str = Field(..., min_length=1, max_length=255)


class CreateConversationRequest(BaseModel):
    """Payload to create a new conversation."""

    title: str | None = Field(default=None, max_length=255)


class ConversationDetailResponse(BaseModel):
    """Detailed conversation session with messages."""

    id: str
    title: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageItem]


class SSEEvent(BaseModel):
    """Server-Sent Event envelope helper."""

    type: str  # 'token', 'done', 'error'
    content: str | None = None
    conversation_id: str | None = None
    response: str | None = None
    citations: list[CitationItem] | None = None
    message: str | None = None

    def to_sse(self) -> str:
        data = self.model_dump(exclude_none=True)
        return f"data: {json.dumps(data)}\n\n"
