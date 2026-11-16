"""Unit and API tests for AI Service admin endpoints (T6.5)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.main import create_app
from app.models.agent import AgentExecution
from app.models.approval import PendingApproval
from app.models.chat import ChatMessage, ChatUserReference, Conversation


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


def make_admin_token(user_id: str = "admin-1", roles: list[str] | None = None) -> str:
    settings = get_settings()
    payload = {
        "sub": user_id,
        "roles": roles or ["ADMIN"],
        "sid": "session-admin",
        "exp": 9999999999,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def test_ai_admin_endpoints(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)

    # 1. Populate test data
    user_ref = ChatUserReference(
        id="ref-1",
        banking_user_id="cust-101",
        role_snapshot="CUSTOMER",
        display_name_masked="Alice C.",
    )
    session.add(user_ref)

    conv = Conversation(
        id="conv-101",
        user_ref_id="ref-1",
        title="Check Balance & Transfer",
        status="ACTIVE",
    )
    session.add(conv)

    msg1 = ChatMessage(
        id="msg-1",
        conversation_id="conv-101",
        role="user",
        content_masked="Transfer ₹5,000 to Bob",
    )
    msg2 = ChatMessage(
        id="msg-2",
        conversation_id="conv-101",
        role="assistant",
        content_masked="Please review transfer to Bob account XXXXXX1234",
    )
    session.add_all([msg1, msg2])

    execution = AgentExecution(
        id="exec-1",
        conversation_id="conv-101",
        message_id="msg-1",
        node="supervisor",
        route="banking_ops",
        tool_name="get_accounts",
        tool_args_masked='{"user_id": "[MASKED]"}',
        status="SUCCESS",
        latency_ms=120,
        token_usage=250,
    )
    session.add(execution)

    from datetime import UTC, datetime, timedelta

    approval = PendingApproval(
        id="appr-1",
        conversation_id="conv-101",
        thread_id="thread-101",
        workflow_type="TRANSFER",
        risk_level="FINANCIAL",
        summary_masked_json='{"amount": "₹5,000"}',
        summary_hash="sha256:abc",
        status="PENDING",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    session.add(approval)
    session.commit()

    admin_token = make_admin_token()
    auditor_token = make_admin_token(user_id="auditor-1", roles=["AUDITOR"])
    customer_token = make_admin_token(user_id="cust-1", roles=["CUSTOMER"])

    # 2. Test Customer blocked (403)
    res_forbidden = client.get("/api/v1/admin/ai-stats", headers={"Authorization": f"Bearer {customer_token}"})
    assert res_forbidden.status_code == 403

    # 3. Test AI Stats (Admin & Auditor)
    res_stats = client.get("/api/v1/admin/ai-stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_stats.status_code == 200
    stats_data = res_stats.json()
    assert stats_data["total_conversations"] == 1
    assert stats_data["total_messages"] == 2
    assert stats_data["total_agent_executions"] == 1
    assert stats_data["total_pending_approvals"] == 1
    assert stats_data["active_pending_approvals"] == 1
    assert stats_data["avg_latency_ms"] == 120.0

    # 4. Test Masked Conversations List
    res_convs = client.get("/api/v1/admin/conversations", headers={"Authorization": f"Bearer {auditor_token}"})
    assert res_convs.status_code == 200
    conv_items = res_convs.json()
    assert len(conv_items) == 1
    assert conv_items[0]["id"] == "conv-101"
    assert conv_items[0]["banking_user_id"] == "cust-101"
    assert conv_items[0]["message_count"] == 2

    # 5. Test Conversation Messages
    res_msgs = client.get("/api/v1/admin/conversations/conv-101/messages", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_msgs.status_code == 200
    msgs = res_msgs.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert "Bob" in msgs[0]["content_masked"]

    # 6. Test Agent Executions
    res_execs = client.get("/api/v1/admin/agent-executions", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_execs.status_code == 200
    exec_items = res_execs.json()
    assert len(exec_items) == 1
    assert exec_items[0]["node"] == "supervisor"
    assert exec_items[0]["tool_name"] == "get_accounts"
    assert exec_items[0]["latency_ms"] == 120

    # 7. Test AI Config GET
    res_cfg = client.get("/api/v1/admin/ai-config", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_cfg.status_code == 200
    cfg = res_cfg.json()
    assert "llm_model" in cfg
    assert "rag_top_k" in cfg

    # 8. Test AI Config PATCH (Admin only)
    patch_payload = {
        "llm_model": "gpt-4o",
        "llm_temperature": 0.2,
        "rag_top_k": 8,
        "rag_min_score": 0.45,
    }
    # Auditor cannot patch (403)
    res_audit_patch = client.patch(
        "/api/v1/admin/ai-config",
        json=patch_payload,
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert res_audit_patch.status_code == 403

    # Admin can patch (200)
    res_patch = client.patch(
        "/api/v1/admin/ai-config",
        json=patch_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_patch.status_code == 200
    updated_cfg = res_patch.json()
    assert updated_cfg["llm_model"] == "gpt-4o"
    assert updated_cfg["llm_temperature"] == 0.2
    assert updated_cfg["rag_top_k"] == 8
    assert updated_cfg["rag_min_score"] == 0.45
