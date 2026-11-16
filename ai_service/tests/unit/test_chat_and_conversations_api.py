"""Unit and API tests for chat streaming and conversations CRUD (T4.6)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import AISettings
from app.db.base import Base
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.main import create_app
from app.models.agent import AgentExecution
from app.models.chat import ChatMessage, Conversation


@pytest.fixture
def test_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session, session_factory
    finally:
        session.close()


def make_token(user_id: str = "user-123", roles: list[str] | None = None) -> str:
    from app.core.config import get_settings
    settings = get_settings()
    payload = {
        "sub": user_id,
        "roles": roles or ["CUSTOMER"],
        "sid": "session-1",
        "exp": 9999999999,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def test_conversations_crud_and_ownership(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)
    token_u1 = make_token(user_id="user-1")
    token_u2 = make_token(user_id="user-2")

    headers_u1 = {"Authorization": f"Bearer {token_u1}"}
    headers_u2 = {"Authorization": f"Bearer {token_u2}"}

    # 1. Create Conversation
    create_resp = client.post(
        "/api/v1/conversations",
        json={"title": "Housing Loan Chat"},
        headers=headers_u1,
    )
    assert create_resp.status_code == 201
    conv_id = create_resp.json()["id"]
    assert create_resp.json()["title"] == "Housing Loan Chat"

    # 2. List Conversations for user 1
    list_resp = client.get("/api/v1/conversations", headers=headers_u1)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
    assert list_resp.json()["items"][0]["id"] == conv_id

    # 3. Search query q
    search_resp = client.get("/api/v1/conversations?q=Housing", headers=headers_u1)
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] == 1

    search_nomatch = client.get("/api/v1/conversations?q=Car", headers=headers_u1)
    assert search_nomatch.status_code == 200
    assert search_nomatch.json()["total"] == 0

    # 4. User 2 cannot access user 1's conversation (Ownership isolation: 404)
    cross_resp = client.get(f"/api/v1/conversations/{conv_id}", headers=headers_u2)
    assert cross_resp.status_code == 404

    # 5. Rename Conversation
    patch_resp = client.patch(
        f"/api/v1/conversations/{conv_id}",
        json={"title": "Updated Loan Title"},
        headers=headers_u1,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Updated Loan Title"

    # 6. Delete Conversation (Soft Delete)
    del_resp = client.delete(f"/api/v1/conversations/{conv_id}", headers=headers_u1)
    assert del_resp.status_code == 204

    # Now 404 on get
    get_after_del = client.get(f"/api/v1/conversations/{conv_id}", headers=headers_u1)
    assert get_after_del.status_code == 404


def test_chat_sse_stream_and_agent_execution_logging(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)
    token = make_token(user_id="user-stream-test")
    headers = {"Authorization": f"Bearer {token}"}

    # Post message to chat stream
    resp = client.post(
        "/api/v1/chat/messages",
        json={"message": "What is my account balance?"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events_raw = resp.text
    assert "event: status" in events_raw
    assert "event: done" in events_raw

    # Verify conversation & messages were persisted in database
    conversations = list(session.execute(select(Conversation)).scalars().all())
    assert len(conversations) >= 1
    conv = conversations[0]

    messages = list(
        session.execute(
            select(ChatMessage).where(ChatMessage.conversation_id == conv.id)
        ).scalars().all()
    )
    assert len(messages) >= 2  # user message and assistant message
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles

    # Verify agent_execution entries were logged
    executions = list(
        session.execute(
            select(AgentExecution).where(AgentExecution.conversation_id == conv.id)
        ).scalars().all()
    )
    assert len(executions) >= 1
    nodes_executed = [e.node for e in executions]
    assert "input_guard" in nodes_executed or "supervisor" in nodes_executed
