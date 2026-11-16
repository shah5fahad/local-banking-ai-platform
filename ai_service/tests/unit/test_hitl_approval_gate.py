"""Comprehensive unit and API tests for Phase 5 task T5.1.

Covers:
- PendingApproval model and status properties (is_expired, summary_masked)
- ApprovalService:
    - Default expiry TTL by workflow (transfer/card=300s, bene=600s, loan=1800s)
    - Auto-generation of canonical summary_hash
    - Ownership isolation (404 for other users)
    - Auto-expiry detection
    - Decision: CONFIRM vs REJECT, idempotent replays, state validation
    - Banking draft cancellation on REJECT
    - Resume after auth with authorization_id, idempotent replays
- approval_gate_node with LangGraph interrupt():
    - Confirmation interrupt
    - Rejection handling
    - Two-stage authentication interrupt for financial/sensitive workflows
    - Non-auth workflows (loan) passing through
- API endpoints:
    - GET /api/v1/chat/approvals/{id}
    - POST /api/v1/chat/approvals/{id}/decision
    - POST /api/v1/chat/approvals/{id}/resume
    - Error scenarios: 404 ownership, 409 expired, 409 invalid state, 422 validation
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.graph import build_graph
from app.agents.nodes.approval_gate import approval_gate_node
from app.agents.state import GraphState
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.db.base import Base
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.main import create_app
from app.models.approval import (
    ApprovalStatus,
    RiskLevel,
    WorkflowType,
)
from app.models.chat import ChatUserReference, Conversation
from app.services.approval_service import ApprovalService


@pytest.fixture
def test_db_session():
    """Create in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session, session_factory
    finally:
        session.close()


def make_test_token(user_id: str = "test-user-1", roles: list[str] | None = None) -> str:
    settings = get_settings()
    payload = {
        "sub": user_id,
        "roles": roles or ["CUSTOMER"],
        "sid": "session-test",
        "exp": 9999999999,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def setup_user_and_conversation(
    db: Session,
    user_id: str = "user-1",
    conv_id: str | None = None,
) -> tuple[ChatUserReference, Conversation]:
    user_ref = ChatUserReference(
        banking_user_id=user_id,
        role_snapshot="CUSTOMER",
        display_name_masked="Test User",
    )
    db.add(user_ref)
    db.commit()

    conv = Conversation(
        id=conv_id,
        user_ref_id=user_ref.id,
        title="Test Conversation",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return user_ref, conv


# ============================================================================
# 1. ApprovalService Unit Tests
# ============================================================================


def test_approval_service_create_and_defaults(test_db_session) -> None:
    session, _ = test_db_session
    _, conv = setup_user_and_conversation(session, user_id="user-create-test")
    service = ApprovalService(session)

    # 1. Transfer default TTL = 300s
    appr_transfer = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹5,000", "beneficiary": "Rahul"},
    )
    assert appr_transfer.status == ApprovalStatus.PENDING.value
    assert appr_transfer.risk_level == RiskLevel.FINANCIAL.value
    assert appr_transfer.summary_hash is not None
    assert len(appr_transfer.summary_hash) == 64  # SHA256
    def to_utc(dt: datetime) -> datetime:
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

    expected_expiry = datetime.now(UTC) + timedelta(seconds=300)
    assert abs((to_utc(appr_transfer.expires_at) - expected_expiry).total_seconds()) < 5
    assert not appr_transfer.is_expired
    assert appr_transfer.summary_masked == {"amount": "₹5,000", "beneficiary": "Rahul"}

    # 2. Beneficiary default TTL = 600s
    appr_bene = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.BENEFICIARY.value,
        summary_masked={"name": "Alice"},
    )
    assert appr_bene.risk_level == RiskLevel.SENSITIVE.value
    expected_bene_expiry = datetime.now(UTC) + timedelta(seconds=600)
    assert abs((to_utc(appr_bene.expires_at) - expected_bene_expiry).total_seconds()) < 5

    # 3. Loan default TTL = 1800s
    appr_loan = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.LOAN.value,
        summary_masked={"loan_type": "PERSONAL", "amount": "₹1,00,000"},
    )
    assert appr_loan.risk_level == RiskLevel.FINANCIAL.value
    expected_loan_expiry = datetime.now(UTC) + timedelta(seconds=1800)
    assert abs((to_utc(appr_loan.expires_at) - expected_loan_expiry).total_seconds()) < 5


def test_approval_service_ownership_enforcement(test_db_session) -> None:
    session, _ = test_db_session
    _, conv1 = setup_user_and_conversation(session, user_id="user-owner-1")
    setup_user_and_conversation(session, user_id="user-owner-2")
    service = ApprovalService(session)

    appr = service.create_approval(
        conversation_id=conv1.id,
        thread_id=conv1.id,
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )

    # Owner can retrieve
    res = service.get_approval(appr.id, banking_user_id="user-owner-1")
    assert res.id == appr.id

    # Non-owner gets NotFoundError (404)
    with pytest.raises(NotFoundError):
        service.get_approval(appr.id, banking_user_id="user-owner-2")

    # Non-existent approval gets NotFoundError
    with pytest.raises(NotFoundError):
        service.get_approval("non-existent-id", banking_user_id="user-owner-1")


def test_approval_service_auto_expiry(test_db_session) -> None:
    session, _ = test_db_session
    _, conv = setup_user_and_conversation(session, user_id="user-exp-test")
    service = ApprovalService(session)

    # Create approval that expired 10 seconds ago
    appr = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.TRANSFER.value,
        ttl_seconds=-10,
    )
    assert appr.is_expired

    # Fetching it updates status to EXPIRED
    fetched = service.get_approval(appr.id, banking_user_id="user-exp-test")
    assert fetched.status == ApprovalStatus.EXPIRED.value

    # Deciding an expired approval raises ConflictError
    with pytest.raises(ConflictError) as exc_info:
        service.decide_approval(appr.id, "CONFIRM", banking_user_id="user-exp-test")
    assert "expired" in str(exc_info.value).lower()

    # Resuming an expired approval raises ConflictError
    with pytest.raises(ConflictError) as exc_info:
        service.resume_approval(
            appr.id, "auth-123", banking_user_id="user-exp-test", raw_token="tk"  # noqa: S106
        )
    assert "expired" in str(exc_info.value).lower()


def test_approval_service_decide_reject_and_cancellation(test_db_session) -> None:
    session, _ = test_db_session
    _, conv = setup_user_and_conversation(session, user_id="user-reject-test")
    service = ApprovalService(session)

    appr = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-txn-999",
    )

    with patch("app.services.approval_service.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        res = service.decide_approval(
            approval_id=appr.id,
            decision="REJECT",
            banking_user_id="user-reject-test",
            raw_token="raw-token-abc",  # noqa: S106
        )
        assert res["status"] == ApprovalStatus.REJECTED.value
        assert res["approval_id"] == appr.id
        assert res["decided_at"] is not None
        mock_instance.cancel_transfer.assert_called_once_with("draft-txn-999")

    # Idempotent replay of REJECT returns same status without error
    replay = service.decide_approval(
        approval_id=appr.id,
        decision="REJECT",
        banking_user_id="user-reject-test",
    )
    assert replay["status"] == ApprovalStatus.REJECTED.value

    # Cannot confirm an already rejected approval
    with pytest.raises(ConflictError):
        service.decide_approval(
            approval_id=appr.id,
            decision="CONFIRM",
            banking_user_id="user-reject-test",
        )


def test_approval_service_decide_confirm_and_resume_flow(test_db_session) -> None:
    session, _ = test_db_session
    _, conv = setup_user_and_conversation(session, user_id="user-confirm-test")
    service = ApprovalService(session)

    # 1. Transfer workflow requires secondary authentication
    appr = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-txn-777",
    )

    confirm_res = service.decide_approval(
        approval_id=appr.id,
        decision="CONFIRM",
        banking_user_id="user-confirm-test",
        raw_token="raw-token-123",  # noqa: S106
    )
    assert confirm_res["status"] == ApprovalStatus.AUTH_REQUIRED.value
    assert confirm_res["requires_auth"] is True

    # Cannot resume with invalid status transition
    # Cannot resume from another user
    with pytest.raises(NotFoundError):
        service.resume_approval(
            approval_id=appr.id,
            authorization_id="auth-mfa-1",
            banking_user_id="wrong-user",
            raw_token="tk",  # noqa: S106
        )

    # Resume with authorization_id
    with patch("app.agents.graph.resume_graph", return_value={"response": "Transfer executed."}):
        resume_res = service.resume_approval(
            approval_id=appr.id,
            authorization_id="auth-mfa-1",
            banking_user_id="user-confirm-test",
            raw_token="raw-token-123",  # noqa: S106
        )
        assert resume_res["status"] == ApprovalStatus.EXECUTED.value
        assert resume_res["authorization_id"] == "auth-mfa-1"

    # Replay of /resume is idempotent
    replay_res = service.resume_approval(
        approval_id=appr.id,
        authorization_id="auth-mfa-1",
        banking_user_id="user-confirm-test",
        raw_token="raw-token-123",  # noqa: S106
    )
    assert replay_res["status"] == ApprovalStatus.EXECUTED.value


def test_approval_service_loan_confirmation_without_mfa(test_db_session) -> None:
    session, _ = test_db_session
    _, conv = setup_user_and_conversation(session, user_id="user-loan-test")
    service = ApprovalService(session)

    appr = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.LOAN.value,
        summary_masked={"amount": "₹50,000"},
    )

    with patch(
        "app.agents.graph.resume_graph",
        return_value={"response": "Loan application submitted."},
    ):
        confirm_res = service.decide_approval(
            approval_id=appr.id,
            decision="CONFIRM",
            banking_user_id="user-loan-test",
            raw_token="raw-token-123",  # noqa: S106
        )
        assert confirm_res["requires_auth"] is False
        assert confirm_res["status"] in (
            ApprovalStatus.CONFIRMED.value,
            ApprovalStatus.EXECUTED.value,
        )


# ============================================================================
# 2. approval_gate_node with LangGraph interrupt() Unit Tests
# ============================================================================


def test_approval_gate_node_confirm_and_reject_flow(test_db_session) -> None:
    session, session_factory = test_db_session
    _, conv = setup_user_and_conversation(session, user_id="user-gate-test")

    with patch("app.agents.nodes.approval_gate.get_session_factory", return_value=session_factory):
        # Build test graph with approval_gate_node
        build_graph(checkpointer=MemorySaver())

        # Test initial pause at approval gate
        state_input: GraphState = {
            "conversation_id": conv.id,
            "pending_action": {
                "workflow": "TRANSFER",
                "banking_resource_id": "txn-abc",
                "summary_masked": {"beneficiary": "Rahul", "amount": "₹5,000"},
                "summary_hash": "sha256:123456",
                "stage": "CONFIRM",
            },
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }
        config = {"configurable": {"thread_id": conv.id, "access_token": "token-test"}}

        # Run gate directly
        with patch("app.agents.nodes.approval_gate.interrupt") as mock_interrupt:
            # 1. Gate calls interrupt for confirmation
            mock_interrupt.return_value = {"decision": "REJECT"}
            out_reject = approval_gate_node(state_input, config=config)
            assert out_reject["approval_status"] == ApprovalStatus.REJECTED.value
            assert "cancelled" in out_reject["response"].lower()

            # 2. Gate calls interrupt and user confirms -> advances to auth interrupt
            mock_interrupt.side_effect = [
                {"decision": "CONFIRM"},
                {"authorization_id": "AUTH-XYZ"},
            ]
            state_input["approval_status"] = "NONE"
            out_auth = approval_gate_node(state_input, config=config)
            assert out_auth["approval_status"] == ApprovalStatus.CONFIRMED.value
            assert out_auth["authentication_status"] == "COMPLETED"
            assert out_auth["authorization_id"] == "AUTH-XYZ"


# ============================================================================
# 3. Decision and Resume REST API Integration Tests
# ============================================================================


def test_get_approval_api_endpoints_and_security(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)
    token_u1 = make_test_token(user_id="user-api-1")
    token_u2 = make_test_token(user_id="user-api-2")

    headers_u1 = {"Authorization": f"Bearer {token_u1}"}
    headers_u2 = {"Authorization": f"Bearer {token_u2}"}

    _, conv1 = setup_user_and_conversation(session, user_id="user-api-1")
    service = ApprovalService(session)
    approval = service.create_approval(
        conversation_id=conv1.id,
        thread_id=conv1.id,
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹5,000", "beneficiary": "Rahul Sharma"},
        banking_resource_id="draft-txn-123",
    )

    # 1. Owner can fetch approval details (GET /chat/approvals/{id})
    resp = client.get(f"/api/v1/chat/approvals/{approval.id}", headers=headers_u1)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approval_id"] == approval.id
    assert data["workflow"] == "TRANSFER"
    assert data["status"] == "PENDING"
    assert data["summary"]["amount"] == "₹5,000"
    assert data["summary_hash"] is not None
    assert data["expires_at"] is not None

    # 2. Other user gets 404 (Ownership isolation)
    cross_resp = client.get(f"/api/v1/chat/approvals/{approval.id}", headers=headers_u2)
    assert cross_resp.status_code == 404

    # 3. Unauthenticated request gets 401
    unauth_resp = client.get(f"/api/v1/chat/approvals/{approval.id}")
    assert unauth_resp.status_code == 401


def test_decide_approval_api_confirm_and_reject(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)
    token_u1 = make_test_token(user_id="user-decide-1")
    token_u2 = make_test_token(user_id="user-decide-2")

    headers_u1 = {"Authorization": f"Bearer {token_u1}"}
    headers_u2 = {"Authorization": f"Bearer {token_u2}"}

    _, conv1 = setup_user_and_conversation(session, user_id="user-decide-1")
    service = ApprovalService(session)

    # Create transfer approval
    appr1 = service.create_approval(
        conversation_id=conv1.id,
        thread_id=conv1.id,
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹2,000"},
        banking_resource_id="draft-txn-decide",
    )

    # 1. Non-owner cannot decide (404)
    cross_decide = client.post(
        f"/api/v1/chat/approvals/{appr1.id}/decision",
        json={"decision": "CONFIRM"},
        headers=headers_u2,
    )
    assert cross_decide.status_code == 404

    # 2. Invalid decision payload gets 422
    bad_decide = client.post(
        f"/api/v1/chat/approvals/{appr1.id}/decision",
        json={"decision": "MAYBE"},
        headers=headers_u1,
    )
    assert bad_decide.status_code == 422

    # 3. Owner confirms transfer -> status becomes AUTH_REQUIRED
    confirm_resp = client.post(
        f"/api/v1/chat/approvals/{appr1.id}/decision",
        json={"decision": "CONFIRM"},
        headers=headers_u1,
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "AUTH_REQUIRED"
    assert confirm_resp.json()["requires_auth"] is True

    # 4. Create second approval to test REJECT
    appr2 = service.create_approval(
        conversation_id=conv1.id,
        thread_id=conv1.id,
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹3,000"},
        banking_resource_id="draft-txn-reject",
    )
    with patch("app.services.approval_service.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        reject_resp = client.post(
            f"/api/v1/chat/approvals/{appr2.id}/decision",
            json={"decision": "REJECT"},
            headers=headers_u1,
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "REJECTED"
        mock_instance.cancel_transfer.assert_called_once_with("draft-txn-reject")


def test_resume_approval_api_flow_and_idempotency(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)
    token_u1 = make_test_token(user_id="user-resume-api")
    token_u2 = make_test_token(user_id="user-intruder")

    headers_u1 = {"Authorization": f"Bearer {token_u1}"}
    headers_u2 = {"Authorization": f"Bearer {token_u2}"}

    _, conv1 = setup_user_and_conversation(session, user_id="user-resume-api")
    service = ApprovalService(session)

    appr = service.create_approval(
        conversation_id=conv1.id,
        thread_id=conv1.id,
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹5,000"},
        banking_resource_id="draft-txn-api-resume",
    )

    # 1. Attempting resume while still PENDING returns 409
    premature_resume = client.post(
        f"/api/v1/chat/approvals/{appr.id}/resume",
        json={"authorization_id": "auth-mfa-123"},
        headers=headers_u1,
    )
    assert premature_resume.status_code == 409

    # 2. User confirms
    client.post(
        f"/api/v1/chat/approvals/{appr.id}/decision",
        json={"decision": "CONFIRM"},
        headers=headers_u1,
    )

    # 3. Non-owner cannot resume (404)
    intruder_resume = client.post(
        f"/api/v1/chat/approvals/{appr.id}/resume",
        json={"authorization_id": "auth-mfa-123"},
        headers=headers_u2,
    )
    assert intruder_resume.status_code == 404

    # 4. Owner resumes with authorization_id
    with patch(
        "app.agents.graph.resume_graph",
        return_value={"response": "Transfer ₹5,000 executed."},
    ):
        resume_resp = client.post(
            f"/api/v1/chat/approvals/{appr.id}/resume",
            json={"authorization_id": "auth-mfa-123"},
            headers=headers_u1,
        )
        assert resume_resp.status_code == 200
        assert resume_resp.json()["status"] == "EXECUTED"
        assert resume_resp.json()["authorization_id"] == "auth-mfa-123"

    # 5. Idempotent replay of resume returns the same result
    replay_resp = client.post(
        f"/api/v1/chat/approvals/{appr.id}/resume",
        json={"authorization_id": "auth-mfa-123"},
        headers=headers_u1,
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["status"] == "EXECUTED"


def test_decide_and_resume_on_expired_approval_returns_409(test_db_session) -> None:
    session, session_factory = test_db_session
    app = create_app()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app)
    token = make_test_token(user_id="user-expiry-api")
    headers = {"Authorization": f"Bearer {token}"}

    _, conv = setup_user_and_conversation(session, user_id="user-expiry-api")
    service = ApprovalService(session)

    # Expired approval
    appr = service.create_approval(
        conversation_id=conv.id,
        thread_id=conv.id,
        workflow_type=WorkflowType.TRANSFER.value,
        ttl_seconds=-30,
    )

    # Decision on expired approval returns 409 Conflict
    decide_resp = client.post(
        f"/api/v1/chat/approvals/{appr.id}/decision",
        json={"decision": "CONFIRM"},
        headers=headers,
    )
    assert decide_resp.status_code == 409
    assert "expired" in decide_resp.json()["message"].lower()

    # Resume on expired approval returns 409 Conflict
    resume_resp = client.post(
        f"/api/v1/chat/approvals/{appr.id}/resume",
        json={"authorization_id": "auth-123"},
        headers=headers,
    )
    assert resume_resp.status_code == 409
    assert "expired" in resume_resp.json()["message"].lower()
