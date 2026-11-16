"""Conversations REST API endpoints."""
from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import AISettings, get_settings
from app.core.errors import NotFoundError, UnauthorizedError
from app.core.security import decode_banking_jwt, extract_roles, extract_user_id
from app.db.session import get_db
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import (
    ConversationDetailResponse,
    ConversationItem,
    ConversationListResponse,
    CreateConversationRequest,
    MessageItem,
    UpdateTitleRequest,
)

logger = logging.getLogger(__name__)

bearer_auth = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_current_user_and_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    settings: AISettings = Depends(get_settings),
) -> tuple[dict, str]:
    """Validate JWT and extract claims and raw token."""
    if not credentials:
        raise UnauthorizedError("Authentication token required")
    payload = decode_banking_jwt(credentials.credentials, settings)
    return payload, credentials.credentials


UserAuth = Annotated[tuple[dict, str], Depends(get_current_user_and_token)]
DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[AISettings, Depends(get_settings)]


def _get_user_ref(user_auth: UserAuth, db: Session):
    payload, _ = user_auth
    user_id = extract_user_id(payload)
    roles = extract_roles(payload)
    role_snapshot = roles[0] if roles else "CUSTOMER"
    repo = ConversationRepository(db)
    return repo.get_or_create_user_ref(
        banking_user_id=user_id,
        role_snapshot=role_snapshot,
        display_name_masked=f"User {user_id[-4:] if len(user_id) >= 4 else user_id}",
    )


@router.get("", response_model=ConversationListResponse, summary="List user conversations")
@router.get("/", response_model=ConversationListResponse, include_in_schema=False)
def list_conversations(
    user_auth: UserAuth,
    db: DbSession,
    q: str | None = Query(None, description="Search term for title"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> ConversationListResponse:
    """List active conversations owned by the authenticated customer."""
    user_ref = _get_user_ref(user_auth, db)
    repo = ConversationRepository(db)
    items, total = repo.list_conversations(user_ref.id, page=page, page_size=page_size, q=q)

    conversation_items = [
        ConversationItem(
            id=c.id,
            title=c.title,
            status=c.status,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=len(c.messages) if c.messages else 0,
        )
        for c in items
    ]

    return ConversationListResponse(
        items=conversation_items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=ConversationItem,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
@router.post(
    "/",
    response_model=ConversationItem,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_conversation(
    body: CreateConversationRequest,
    user_auth: UserAuth,
    db: DbSession,
) -> ConversationItem:
    """Create a new conversation session for the customer."""
    user_ref = _get_user_ref(user_auth, db)
    repo = ConversationRepository(db)
    conv = repo.create_conversation(user_ref_id=user_ref.id, title=body.title)
    db.commit()
    db.refresh(conv)

    return ConversationItem(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=0,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Get conversation details with messages",
)
def get_conversation(
    conversation_id: str,
    user_auth: UserAuth,
    db: DbSession,
) -> ConversationDetailResponse:
    """Retrieve conversation and its messages with timestamps."""
    user_ref = _get_user_ref(user_auth, db)
    repo = ConversationRepository(db)
    conv = repo.get_conversation(conversation_id, user_ref_id=user_ref.id)
    if not conv:
        raise NotFoundError("Conversation", conversation_id)

    messages_raw = repo.list_messages(conversation_id, page=1, page_size=100)
    message_items = []
    for m in messages_raw:
        cits = None
        if m.citations_json:
            try:
                cits = json.loads(m.citations_json)
            except Exception:
                cits = None
        message_items.append(
            MessageItem(
                id=m.id,
                role=m.role,
                content_masked=m.content_masked,
                citations=cits,
                created_at=m.created_at,
            )
        )

    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=message_items,
    )


@router.patch(
    "/{conversation_id}",
    response_model=ConversationItem,
    summary="Rename conversation title",
)
def rename_conversation(
    conversation_id: str,
    body: UpdateTitleRequest,
    user_auth: UserAuth,
    db: DbSession,
) -> ConversationItem:
    """Rename a conversation title."""
    user_ref = _get_user_ref(user_auth, db)
    repo = ConversationRepository(db)
    conv = repo.update_conversation_title(
        conversation_id=conversation_id,
        user_ref_id=user_ref.id,
        title=body.title,
    )
    if not conv:
        raise NotFoundError("Conversation", conversation_id)

    db.commit()
    db.refresh(conv)

    return ConversationItem(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(conv.messages) if conv.messages else 0,
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversation (soft delete)",
)
def delete_conversation(
    conversation_id: str,
    user_auth: UserAuth,
    db: DbSession,
) -> Response:
    """Soft delete a conversation."""
    user_ref = _get_user_ref(user_auth, db)
    repo = ConversationRepository(db)
    success = repo.soft_delete_conversation(conversation_id, user_ref_id=user_ref.id)
    if not success:
        raise NotFoundError("Conversation", conversation_id)

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
