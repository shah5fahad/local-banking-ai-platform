"""Admin API router for AI service statistics, masked chat monitor, agent execution traces, and config."""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import AISettings, get_settings
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import decode_banking_jwt, extract_roles, extract_user_id
from app.db.session import get_db
from app.models.agent import AgentExecution
from app.models.approval import PendingApproval
from app.models.chat import ChatMessage, ChatUserReference, Conversation
from app.schemas.admin import (
    AdminConversationItem,
    AdminMessageItem,
    AgentExecutionItem,
    AIConfigResponse,
    AIStatsResponse,
    UpdateAIConfigRequest,
)

logger = logging.getLogger(__name__)

bearer_auth = HTTPBearer(auto_error=False)


def require_admin_or_auditor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    settings: AISettings = Depends(get_settings),
) -> str:
    """Authorize access for admin or auditor."""
    if x_service_key and x_service_key == settings.service_key:
        return "service:admin"

    if credentials:
        payload = decode_banking_jwt(credentials.credentials, settings)
        roles = [r.upper() for r in extract_roles(payload)]
        if "ADMIN" in roles or "AUDITOR" in roles or payload.get("is_admin") is True:
            return extract_user_id(payload)
        raise ForbiddenError("Admin or Auditor access required")

    raise UnauthorizedError("Authentication required")


def require_admin_only(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    settings: AISettings = Depends(get_settings),
) -> str:
    """Authorize access for admin only."""
    if x_service_key and x_service_key == settings.service_key:
        return "service:admin"

    if credentials:
        payload = decode_banking_jwt(credentials.credentials, settings)
        roles = [r.upper() for r in extract_roles(payload)]
        if "ADMIN" in roles or payload.get("is_admin") is True:
            return extract_user_id(payload)
        raise ForbiddenError("Admin access required")

    raise UnauthorizedError("Authentication required")


AdminOrAuditorUser = Annotated[str, Depends(require_admin_or_auditor)]
AdminOnlyUser = Annotated[str, Depends(require_admin_only)]
DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[AISettings, Depends(get_settings)]

router = APIRouter(prefix="/admin", tags=["admin-ai"])


@router.get("/ai-stats", response_model=AIStatsResponse, summary="Get AI system usage statistics")
def get_ai_stats(
    _user: AdminOrAuditorUser,
    db: DbSession,
) -> AIStatsResponse:
    """Aggregate high-level AI usage metrics across conversations, messages, executions, and approvals."""
    total_convs = db.scalar(select(func.count(Conversation.id))) or 0
    active_convs = (
        db.scalar(select(func.count(Conversation.id)).where(Conversation.status == "ACTIVE")) or 0
    )
    total_msgs = db.scalar(select(func.count(ChatMessage.id))) or 0
    total_execs = db.scalar(select(func.count(AgentExecution.id))) or 0
    avg_lat = db.scalar(
        select(func.avg(AgentExecution.latency_ms)).where(AgentExecution.latency_ms.is_not(None))
    )
    total_approvals = db.scalar(select(func.count(PendingApproval.id))) or 0
    active_approvals = (
        db.scalar(
            select(func.count(PendingApproval.id)).where(PendingApproval.status == "PENDING")
        )
        or 0
    )

    return AIStatsResponse(
        total_conversations=total_convs,
        active_conversations=active_convs,
        total_messages=total_msgs,
        total_agent_executions=total_execs,
        avg_latency_ms=round(float(avg_lat), 1) if avg_lat is not None else None,
        total_pending_approvals=total_approvals,
        active_pending_approvals=active_approvals,
    )


@router.get(
    "/conversations",
    response_model=list[AdminConversationItem],
    summary="List conversations for masked chat monitor",
)
def list_admin_conversations(
    _user: AdminOrAuditorUser,
    db: DbSession,
    status: Optional[str] = Query(None, description="Filter by status (ACTIVE, CLOSED)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[AdminConversationItem]:
    """List conversations across all users with message count and timestamps."""
    stmt = (
        select(
            Conversation,
            ChatUserReference.banking_user_id,
            func.count(ChatMessage.id).label("msg_count"),
        )
        .join(ChatUserReference, Conversation.user_ref_id == ChatUserReference.id)
        .outerjoin(ChatMessage, Conversation.id == ChatMessage.conversation_id)
        .group_by(Conversation.id, ChatUserReference.banking_user_id)
        .order_by(Conversation.updated_at.desc())
    )
    if status:
        stmt = stmt.where(Conversation.status == status)

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    rows = db.execute(stmt).all()
    results: list[AdminConversationItem] = []
    for conv, banking_user_id, msg_count in rows:
        results.append(
            AdminConversationItem(
                id=conv.id,
                banking_user_id=banking_user_id,
                title=conv.title,
                status=conv.status,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=msg_count or 0,
            )
        )
    return results


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[AdminMessageItem],
    summary="Get masked message transcript for audit monitoring",
)
def get_admin_conversation_messages(
    conversation_id: str,
    _user: AdminOrAuditorUser,
    db: DbSession,
) -> list[AdminMessageItem]:
    """Retrieve turn-by-turn messages with PII masking preserved for compliance auditing."""
    conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not conv:
        raise NotFoundError("Conversation", conversation_id)

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = list(db.scalars(stmt).all())
    return [AdminMessageItem.model_validate(m) for m in messages]


@router.get(
    "/agent-executions",
    response_model=list[AgentExecutionItem],
    summary="List LangGraph node execution traces",
)
def list_agent_executions(
    _user: AdminOrAuditorUser,
    db: DbSession,
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    node: Optional[str] = Query(None, description="Filter by LangGraph node name"),
    status: Optional[str] = Query(None, description="Filter by execution status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> list[AgentExecutionItem]:
    """Query step execution history across agent nodes, tools, latency, and status."""
    stmt = select(AgentExecution).order_by(AgentExecution.created_at.desc())
    if conversation_id:
        stmt = stmt.where(AgentExecution.conversation_id == conversation_id)
    if node:
        stmt = stmt.where(AgentExecution.node == node)
    if status:
        stmt = stmt.where(AgentExecution.status == status)

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    executions = list(db.scalars(stmt).all())
    return [AgentExecutionItem.model_validate(ex) for ex in executions]


@router.get(
    "/ai-config",
    response_model=AIConfigResponse,
    summary="Get AI runtime configuration parameters",
)
def get_ai_config(
    _user: AdminOrAuditorUser,
    settings: AppSettings,
) -> AIConfigResponse:
    """Retrieve active non-secret AI runtime settings."""
    return AIConfigResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_temperature=settings.llm_temperature,
        llm_max_tokens=settings.llm_max_tokens,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        rag_top_k=settings.rag_top_k,
        rag_min_score=settings.rag_min_score,
        search_provider=settings.search_provider,
    )


@router.patch(
    "/ai-config",
    response_model=AIConfigResponse,
    summary="Update AI runtime configuration parameters",
)
def update_ai_config(
    data: UpdateAIConfigRequest,
    _admin: AdminOnlyUser,
    settings: AppSettings,
) -> AIConfigResponse:
    """Update non-secret AI runtime configuration parameters."""
    if data.llm_model is not None:
        settings.llm_model = data.llm_model
    if data.llm_temperature is not None:
        settings.llm_temperature = data.llm_temperature
    if data.rag_top_k is not None:
        settings.rag_top_k = data.rag_top_k
    if data.rag_min_score is not None:
        settings.rag_min_score = data.rag_min_score

    return AIConfigResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_temperature=settings.llm_temperature,
        llm_max_tokens=settings.llm_max_tokens,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        rag_top_k=settings.rag_top_k,
        rag_min_score=settings.rag_min_score,
        search_provider=settings.search_provider,
    )
