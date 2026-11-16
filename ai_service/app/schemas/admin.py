"""Pydantic schemas for AI service administrative monitoring and configuration."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AIStatsResponse(BaseModel):
    """Aggregate high-level AI usage metrics."""

    model_config = ConfigDict(from_attributes=True)

    total_conversations: int
    active_conversations: int
    total_messages: int
    total_agent_executions: int
    avg_latency_ms: Optional[float] = None
    total_pending_approvals: int
    active_pending_approvals: int


class AdminConversationItem(BaseModel):
    """Conversation summary item for admin monitoring."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    banking_user_id: str
    title: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class AdminMessageItem(BaseModel):
    """Masked chat message item for auditor and admin review."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content_masked: str
    citations_json: Optional[str] = None
    created_at: datetime


class AgentExecutionItem(BaseModel):
    """LangGraph node execution trace item."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    message_id: Optional[str] = None
    node: str
    route: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args_masked: Optional[str] = None
    status: str
    latency_ms: Optional[int] = None
    token_usage: Optional[int] = None
    error_code: Optional[str] = None
    request_id: Optional[str] = None
    created_at: datetime


class AIConfigResponse(BaseModel):
    """Non-secret AI runtime configuration parameters."""

    model_config = ConfigDict(from_attributes=True)

    llm_provider: str
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    embedding_provider: str
    embedding_model: str
    rag_top_k: int
    rag_min_score: float
    search_provider: str


class UpdateAIConfigRequest(BaseModel):
    """Request schema for updating runtime AI parameters."""

    llm_model: Optional[str] = Field(None, min_length=1)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    rag_top_k: Optional[int] = Field(None, ge=1, le=50)
    rag_min_score: Optional[float] = Field(None, ge=0.0, le=1.0)
