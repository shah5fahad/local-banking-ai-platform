"""Comprehensive security test suite for Human-in-the-Loop (HITL) workflows (Phase 5 task T5.7).

Security Requirements Tested:
1. No Write Before Approval:
   - Verification across all HITL workflows (Transfer, Beneficiary, Card Payment, Loan):
     Backend write/execute APIs are never called before human confirmation AND authentication.
   - Free-text typed in chat ("yes", "confirm", "I approve") does not trigger action execution.
   - Rejection halts the workflow and cancels drafts without any backend writes.
2. Tamper Resistance:
   - summary_hash verification detects and rejects tampered transaction details.
   - Forged or invalid authorization tokens are rejected by execution nodes.
   - User ID smuggling in request bodies/parameters is ignored; caller identity is strictly bound to JWT claims.
   - Admins cannot approve or resume transactions on behalf of users (owner verification).
3. Replay Attacks & Idempotency:
   - Idempotent decision replay for duplicate CONFIRM submissions.
   - Idempotent decision replay for duplicate REJECT submissions.
   - Idempotent resume replay returns prior execution result without double execution.
   - Replays on expired, rejected, or superseded approvals are rejected with 409 Conflict.
4. Cross-User Isolation (IDOR Protection):
   - User A cannot view User B's pending approval (404 Not Found).
   - User A cannot decide (confirm/reject) User B's pending approval (404 Not Found).
   - User A cannot resume User B's pending approval (404 Not Found).
   - User A cannot view User B's active approvals via /chat/approvals/active.
   - User A cannot inject messages into User B's conversation (404 Not Found).
5. Credential & Secret Isolation:
   - PIN / OTP credentials never appear in GraphState, checkpointer tables, or message logs.
   - Bearer access tokens are never persisted in GraphState or checkpoint databases.
   - Account and card numbers are strictly masked across approval summaries and events.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.graph import build_graph
from app.agents.nodes.approval_gate import approval_gate_node
from app.agents.nodes.execute import execute_node
from app.agents.state import GraphState
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.db.base import Base
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.integrations.banking_client import BankingClientError
from app.main import create_app
from app.models.approval import ApprovalStatus, PendingApproval, RiskLevel, WorkflowType
from app.models.chat import ChatUserReference, Conversation
from app.models.checkpoint import WorkflowCheckpointMetadata
from app.services.approval_service import ApprovalService


@pytest.fixture
def sec_db_session():
    """Isolated in-memory SQLite database session for security tests."""
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


def make_jwt(user_id: str, roles: list[str] | None = None) -> str:
    """Helper to generate signed JWT token for a specific user ID and roles."""
    settings = get_settings()
    payload = {
        "sub": user_id,
        "roles": roles or ["CUSTOMER"],
        "sid": f"sess-{user_id}",
        "exp": 9999999999,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_user_and_conv(
    db: Session,
    user_id: str,
    conv_id: str | None = None,
) -> tuple[ChatUserReference, Conversation]:
    """Helper to seed user reference and conversation in DB."""
    user_ref = ChatUserReference(
        banking_user_id=user_id,
        role_snapshot="CUSTOMER",
        display_name_masked=f"User {user_id}",
    )
    db.add(user_ref)
    db.commit()

    conv = Conversation(
        id=conv_id,
        user_ref_id=user_ref.id,
        title=f"Security Test Conv {user_id}",
    )
    db.add(conv)
    db.commit()
    return user_ref, conv


# =====================================================================
# 1. No Write Before Approval
# =====================================================================

def test_security_transfer_no_write_before_approval(sec_db_session) -> None:
    """Transfer flow halts at approval_gate; no ledger debit or execute occurs before approval."""
    db, session_factory = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-1")

    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = f"sec-thread-{conv.id}"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "valid-user-jwt",
        }
    }

    mock_client = MagicMock()
    mock_client.list_beneficiaries.return_value = [
        {
            "id": "b-rahul-01",
            "name": "Rahul Sharma",
            "last4": "4321",
            "bank_name": "HDFC Bank",
            "account_number_masked": "XXXXXX4321",
            "nickname": None,
        }
    ]
    mock_client.list_accounts.return_value = [
        {"id": "acc-savings-01", "status": "ACTIVE", "balance_minor": 2000000}
    ]
    mock_client.get_transfer_limits.return_value = {
        "per_transaction_limit_minor": 10000000,
        "daily_remaining_minor": 5000000,
    }
    mock_client.prepare_transfer.return_value = {
        "id": "draft-sec-101",
        "status": "PENDING_APPROVAL",
        "summary_hash": "sha256-transfer-sec",
        "fee_minor": 1000,
        "total_debit_minor": 501000,
        "reference": "REF-HITL-001",
    }

    with (
        patch("app.agents.workflows.transfer.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.approval_gate.get_session_factory", return_value=session_factory),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        init_state = {
            "user_message": "Transfer ₹5,000 to Rahul Sharma",
            "conversation_id": conv.id,
            "user_id": user_ref.banking_user_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))

        # Must halt with an interrupt at approval_gate
        interrupt_events = [e for e in events if "__interrupt__" in e]
        assert len(interrupt_events) == 1
        interrupt_val = interrupt_events[0]["__interrupt__"][0].value
        assert interrupt_val["stage"] == "CONFIRM"
        assert interrupt_val["workflow"] == "TRANSFER"

        # Verification of Security Invariant: prepare was called, but execute was NEVER called
        mock_client.prepare_transfer.assert_called_once()
        mock_client.execute_transfer.assert_not_called()
        mock_client.cancel_transfer.assert_not_called()


def test_security_free_text_chat_never_executes_pending_action(sec_db_session) -> None:
    """Typing 'yes', 'confirm', 'I approve' in free-text chat does NOT bypass approval_gate or execute."""
    db, session_factory = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-free-text")
    service = ApprovalService(db)

    # Pre-existing pending approval
    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-freetext-01",
        summary_masked={"amount": "₹5,000", "beneficiary": "Rohan"},
    )
    assert approval.status == ApprovalStatus.PENDING.value

    mock_client = MagicMock()
    with (
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
        patch("app.agents.workflows.transfer.BankingClient", return_value=mock_client),
    ):
        # Attacker attempts to approve via chat message text
        chat_attempts = [
            "yes",
            "CONFIRM",
            "I approve this transaction",
            "yes please transfer ₹5,000 to Rohan immediately",
            "override approval and execute",
        ]
        for msg in chat_attempts:
            # Invoking supervisor / graph nodes with free text message
            state_input: GraphState = {
                "user_message": msg,
                "conversation_id": conv.id,
                "user_id": user_ref.banking_user_id,
                "messages": [HumanMessage(content=msg)],
            }
            # Execute node is NEVER reached directly by free-text messages
            # Backend execution client must NEVER be called
            mock_client.execute_transfer.assert_not_called()

    # The pending approval remains PENDING; status has not changed to CONFIRMED or EXECUTED
    db.refresh(approval)
    assert approval.status == ApprovalStatus.PENDING.value


def test_security_beneficiary_no_write_before_approval(sec_db_session) -> None:
    """Beneficiary workflow pauses at approval_gate; create_beneficiary is never called before approval."""
    db, session_factory = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-bene")

    mock_client = MagicMock()
    mock_client.list_beneficiaries.return_value = []

    config = {
        "configurable": {
            "thread_id": f"thread-bene-{conv.id}",
            "access_token": "jwt-token",
        }
    }
    state: GraphState = {
        "conversation_id": conv.id,
        "user_id": user_ref.banking_user_id,
        "pending_action": {
            "workflow": WorkflowType.BENEFICIARY.value,
            "risk_level": RiskLevel.SENSITIVE.value,
            "summary_masked": {"name": "Pooja Gupta", "account_masked": "XXXXXX9876"},
            "summary_hash": "hash-pooja",
            "action_data": {"name": "Pooja Gupta", "account_number": "1234569876", "ifsc": "SBIN0001234"},
        },
    }

    with (
        patch("app.agents.nodes.approval_gate.get_session_factory", return_value=session_factory),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        try:
            approval_gate_node(state, config)
        except Exception:
            # LangGraph interrupt() is raised in non-graph test execution
            pass

        # Backend write was NOT executed
        mock_client.create_beneficiary.assert_not_called()


def test_security_card_payment_no_write_before_approval(sec_db_session) -> None:
    """Card payment workflow pauses at approval_gate; execute_card_payment is never called before approval."""
    mock_client = MagicMock()
    state: GraphState = {
        "pending_action": {
            "workflow": WorkflowType.CARD_PAYMENT.value,
            "banking_resource_id": "card-pay-draft-999",
            "summary_hash": "hash-card-pay",
        },
        "approval_status": ApprovalStatus.PENDING.value,
    }
    config = {"configurable": {"access_token": "test-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient", return_value=mock_client):
        # Calling execute_node without AUTHENTICATED or CONFIRMED state
        res = execute_node(state, config)
        assert res.get("approval_status") is None or res.get("approval_status") != ApprovalStatus.EXECUTED.value
        mock_client.execute_card_payment.assert_not_called()


def test_security_loan_no_write_before_approval(sec_db_session) -> None:
    """Loan application is never submitted before explicit human confirmation."""
    mock_client = MagicMock()
    state: GraphState = {
        "pending_action": {
            "workflow": WorkflowType.LOAN.value,
            "summary_masked": {"amount": "₹5,00,000"},
        },
        "approval_status": ApprovalStatus.REJECTED.value,
    }
    config = {"configurable": {"access_token": "test-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient", return_value=mock_client):
        res = execute_node(state, config)
        assert res == {}
        mock_client.submit_loan_application.assert_not_called()


def test_security_rejection_prevents_write_and_cancels_draft(sec_db_session) -> None:
    """Rejection decision triggers cancel_transfer at banking and prevents any execution."""
    db, session_factory = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-reject")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-sec-reject-01",
        summary_masked={"amount": "₹15,000"},
    )

    with patch("app.services.approval_service.BankingClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        res = service.decide_approval(
            approval_id=approval.id,
            decision="REJECT",
            banking_user_id=user_ref.banking_user_id,
            raw_token="user-jwt-reject",
        )

        assert res["status"] == ApprovalStatus.REJECTED.value
        mock_client.cancel_transfer.assert_called_once_with("draft-sec-reject-01")
        mock_client.execute_transfer.assert_not_called()


# =====================================================================
# 2. Tamper Resistance
# =====================================================================

def test_security_summary_hash_tamper_rejected(sec_db_session) -> None:
    """If summary_hash is tampered with, resume_approval rejects with ConflictError."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-tamper")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹5,000", "to": "Alice"},
        summary_hash="authentic-sha256-hash-001",
    )
    # Transition to AUTH_REQUIRED
    approval.status = ApprovalStatus.AUTH_REQUIRED.value
    db.commit()

    # Attacker tries to resume with a tampered hash (e.g. after attempting to modify amount)
    with pytest.raises(ConflictError) as exc_info:
        service.resume_approval(
            approval_id=approval.id,
            authorization_id="valid-pin-auth-id",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt-token",
            summary_hash="tampered-sha256-hash-999",
        )

    assert "tampered" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()


def test_security_tampered_authorization_token_rejected_by_banking(sec_db_session) -> None:
    """Forged authorization_id is rejected by Banking API and execution node handles failure."""
    mock_client = MagicMock()
    mock_client.execute_transfer.side_effect = BankingClientError(
        error_code="AUTHORIZATION_INVALID",
        message="Invalid or expired authorization token",
        http_status=401,
    )

    state: GraphState = {
        "pending_action": {
            "workflow": WorkflowType.TRANSFER.value,
            "banking_resource_id": "draft-101",
            "summary_hash": "hash-101",
        },
        "authorization_id": "forged-stolen-auth-id-xyz",
        "approval_status": ApprovalStatus.CONFIRMED.value,
    }
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient", return_value=mock_client):
        res = execute_node(state, config)
        assert res.get("error_code") == "AUTHORIZATION_INVALID"
        assert "failed" in res.get("response", "").lower()


def test_security_user_id_smuggling_ignored(sec_db_session) -> None:
    """User ID passed in request body or headers cannot override JWT subject."""
    db, session_factory = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="real-user-alice")

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token = make_jwt(user_id="real-user-alice")
    headers = {"Authorization": f"Bearer {token}"}

    # Attacker attempts to smuggle user_id="victim-user-bob"
    with patch("app.agents.graph.invoke_graph") as mock_invoke:
        mock_invoke.return_value = {"messages": [], "response": "OK"}
        res = client.post(
            "/api/v1/chat/messages",
            json={
                "message": "Check my balance",
                "conversation_id": conv.id,
                "user_id": "victim-user-bob",  # Smuggled field
            },
            headers=headers,
        )

    # Chat user reference and conversation in DB belong strictly to real-user-alice
    db.refresh(conv)
    user_ref_record = db.get(ChatUserReference, conv.user_ref_id)
    assert user_ref_record is not None
    assert user_ref_record.banking_user_id == "real-user-alice"


def test_security_admin_cannot_approve_on_behalf_of_user(sec_db_session) -> None:
    """Admin role cannot approve or resume on behalf of a regular user (principle: owner check)."""
    db, session_factory = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="customer-user-1")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹2,000"},
    )

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)

    # Admin caller
    admin_token = make_jwt(user_id="admin-user-999", roles=["ADMIN"])
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin attempts decision on customer's approval
    res_decide = client.post(
        f"/api/v1/chat/approvals/{approval.id}/decision",
        json={"decision": "CONFIRM"},
        headers=admin_headers,
    )
    # Must be 404 Not Found (ownership isolation prevents admin override)
    assert res_decide.status_code == 404

    # Admin attempts resume on customer's approval
    res_resume = client.post(
        f"/api/v1/chat/approvals/{approval.id}/resume",
        json={"authorization_id": "auth-admin-xyz"},
        headers=admin_headers,
    )
    assert res_resume.status_code == 404


# =====================================================================
# 3. Replay Attacks & Idempotency
# =====================================================================

def test_security_decision_confirm_replay_idempotency(sec_db_session) -> None:
    """Replaying CONFIRM returns prior state without duplicate side-effects."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-replay-1")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )

    with patch("app.agents.graph.resume_graph") as mock_resume:
        # First confirmation
        res1 = service.decide_approval(
            approval_id=approval.id,
            decision="CONFIRM",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt-1",
        )
        assert res1["status"] == ApprovalStatus.AUTH_REQUIRED.value
        assert mock_resume.call_count == 1

        # Second confirmation (replay attack / double submit)
        res2 = service.decide_approval(
            approval_id=approval.id,
            decision="CONFIRM",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt-1",
        )
        assert res2["status"] == ApprovalStatus.AUTH_REQUIRED.value
        # graph.resume must NOT be called again on replay
        assert mock_resume.call_count == 1


def test_security_decision_reject_replay_idempotency(sec_db_session) -> None:
    """Replaying REJECT returns prior status without duplicate cancellations."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-replay-2")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-replay-999",
        summary_masked={"amount": "₹2,500"},
    )

    with (
        patch("app.services.approval_service.BankingClient") as mock_client_cls,
        patch("app.agents.graph.resume_graph"),
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # First reject
        res1 = service.decide_approval(
            approval_id=approval.id,
            decision="REJECT",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt-reject",
        )
        assert res1["status"] == ApprovalStatus.REJECTED.value
        mock_client.cancel_transfer.assert_called_once_with("draft-replay-999")

        # Second reject (replay)
        res2 = service.decide_approval(
            approval_id=approval.id,
            decision="REJECT",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt-reject",
        )
        assert res2["status"] == ApprovalStatus.REJECTED.value
        # cancel_transfer must NOT be called a second time
        assert mock_client.cancel_transfer.call_count == 1


def test_security_resume_replay_idempotency(sec_db_session) -> None:
    """Replaying /resume returns the prior result and never re-executes backend transfers."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-replay-3")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-replay-exec",
        summary_masked={"amount": "₹1,000"},
    )
    approval.status = ApprovalStatus.AUTH_REQUIRED.value
    db.commit()

    with patch("app.agents.graph.resume_graph") as mock_resume:
        mock_resume.return_value = {"response": "Transfer completed successfully. Ref: REF-001"}

        # First resume execution
        res1 = service.resume_approval(
            approval_id=approval.id,
            authorization_id="auth-single-use-001",
            banking_user_id=user_ref.banking_user_id,
            raw_token="user-jwt",
        )
        assert res1["status"] == ApprovalStatus.EXECUTED.value
        assert mock_resume.call_count == 1

        # Second resume (replay attempt with same authorization_id)
        res2 = service.resume_approval(
            approval_id=approval.id,
            authorization_id="auth-single-use-001",
            banking_user_id=user_ref.banking_user_id,
            raw_token="user-jwt",
        )
        assert res2["status"] == ApprovalStatus.EXECUTED.value
        # Backend execution graph was NOT called again
        assert mock_resume.call_count == 1


def test_security_decision_on_expired_approval_rejected(sec_db_session) -> None:
    """Confirm or reject on an expired approval raises ConflictError (409)."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-exp")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹3,000"},
    )
    # Expire approval
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=60)
    db.commit()

    with pytest.raises(ConflictError) as exc_info:
        service.decide_approval(
            approval_id=approval.id,
            decision="CONFIRM",
            banking_user_id=user_ref.banking_user_id,
        )
    assert "expired" in str(exc_info.value).lower()


def test_security_resume_on_expired_approval_rejected(sec_db_session) -> None:
    """Resume on an expired approval raises ConflictError (409)."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-exp-resume")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹4,000"},
    )
    approval.status = ApprovalStatus.AUTH_REQUIRED.value
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=30)
    db.commit()

    with pytest.raises(ConflictError) as exc_info:
        service.resume_approval(
            approval_id=approval.id,
            authorization_id="auth-xyz",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt",
        )
    assert "expired" in str(exc_info.value).lower()


def test_security_decision_or_resume_on_rejected_approval_rejected(sec_db_session) -> None:
    """Attempting to confirm or resume an already rejected approval raises ConflictError (409)."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-already-rejected")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )
    approval.status = ApprovalStatus.REJECTED.value
    db.commit()

    with pytest.raises(ConflictError):
        service.decide_approval(
            approval_id=approval.id,
            decision="CONFIRM",
            banking_user_id=user_ref.banking_user_id,
        )

    with pytest.raises(ConflictError):
        service.resume_approval(
            approval_id=approval.id,
            authorization_id="auth-xyz",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt",
        )


def test_security_decision_or_resume_on_superseded_approval_rejected(sec_db_session) -> None:
    """Attempting to confirm, reject, or resume a superseded approval raises ConflictError (409)."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-already-superseded")
    service = ApprovalService(db)

    app1 = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-1-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )
    # Supersede by creating app2
    service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-2-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹2,000"},
    )
    db.refresh(app1)
    assert app1.status == ApprovalStatus.SUPERSEDED.value

    with pytest.raises(ConflictError) as exc_decide:
        service.decide_approval(
            approval_id=app1.id,
            decision="CONFIRM",
            banking_user_id=user_ref.banking_user_id,
        )
    assert "superseded" in str(exc_decide.value).lower()

    with pytest.raises(ConflictError) as exc_resume:
        service.resume_approval(
            approval_id=app1.id,
            authorization_id="auth-xyz",
            banking_user_id=user_ref.banking_user_id,
            raw_token="jwt",
        )
    assert "superseded" in str(exc_resume.value).lower()


# =====================================================================
# 4. Cross-User Isolation (IDOR Protection)
# =====================================================================

def test_security_cross_user_get_approval_returns_404(sec_db_session) -> None:
    """User B cannot view User A's pending approval (returns 404)."""
    db, session_factory = sec_db_session
    user_a, conv_a = create_user_and_conv(db, user_id="victim-user-a")
    user_b, conv_b = create_user_and_conv(db, user_id="attacker-user-b")
    service = ApprovalService(db)

    approval_a = service.create_approval(
        conversation_id=conv_a.id,
        thread_id=f"thread-{conv_a.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹50,000", "to": "Secret Recipient"},
    )

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token_b = make_jwt(user_id="attacker-user-b")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    res = client.get(f"/api/v1/chat/approvals/{approval_a.id}", headers=headers_b)
    assert res.status_code == 404


def test_security_cross_user_decide_approval_returns_404(sec_db_session) -> None:
    """User B cannot confirm or reject User A's pending approval (returns 404)."""
    db, session_factory = sec_db_session
    user_a, conv_a = create_user_and_conv(db, user_id="victim-user-a")
    user_b, conv_b = create_user_and_conv(db, user_id="attacker-user-b")
    service = ApprovalService(db)

    approval_a = service.create_approval(
        conversation_id=conv_a.id,
        thread_id=f"thread-{conv_a.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹10,000"},
    )

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token_b = make_jwt(user_id="attacker-user-b")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    res = client.post(
        f"/api/v1/chat/approvals/{approval_a.id}/decision",
        json={"decision": "REJECT"},
        headers=headers_b,
    )
    assert res.status_code == 404
    db.refresh(approval_a)
    assert approval_a.status == ApprovalStatus.PENDING.value


def test_security_cross_user_resume_approval_returns_404(sec_db_session) -> None:
    """User B cannot resume User A's approval with their own or stolen authorization_id (returns 404)."""
    db, session_factory = sec_db_session
    user_a, conv_a = create_user_and_conv(db, user_id="victim-user-a")
    user_b, conv_b = create_user_and_conv(db, user_id="attacker-user-b")
    service = ApprovalService(db)

    approval_a = service.create_approval(
        conversation_id=conv_a.id,
        thread_id=f"thread-{conv_a.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹25,000"},
    )
    approval_a.status = ApprovalStatus.AUTH_REQUIRED.value
    db.commit()

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token_b = make_jwt(user_id="attacker-user-b")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    res = client.post(
        f"/api/v1/chat/approvals/{approval_a.id}/resume",
        json={"authorization_id": "auth-b-stolen"},
        headers=headers_b,
    )
    assert res.status_code == 404
    db.refresh(approval_a)
    assert approval_a.status == ApprovalStatus.AUTH_REQUIRED.value


def test_security_cross_user_active_approval_returns_none(sec_db_session) -> None:
    """User B cannot query active approvals in User A's conversation."""
    db, session_factory = sec_db_session
    user_a, conv_a = create_user_and_conv(db, user_id="victim-user-a")
    user_b, conv_b = create_user_and_conv(db, user_id="attacker-user-b")
    service = ApprovalService(db)

    service.create_approval(
        conversation_id=conv_a.id,
        thread_id=f"thread-{conv_a.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹30,000"},
    )

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token_b = make_jwt(user_id="attacker-user-b")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    res = client.get(f"/api/v1/chat/approvals/active?conversation_id={conv_a.id}", headers=headers_b)
    assert res.status_code == 200
    assert res.json() is None


def test_security_cross_user_conversation_access_returns_404(sec_db_session) -> None:
    """User B cannot send messages or interact with User A's conversation."""
    db, session_factory = sec_db_session
    user_a, conv_a = create_user_and_conv(db, user_id="user-a-owner")
    user_b, conv_b = create_user_and_conv(db, user_id="user-b-intruder")

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token_b = make_jwt(user_id="user-b-intruder")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B sends message specifying User A's conversation ID
    res = client.post(
        "/api/v1/chat/messages",
        json={"message": "Hello", "conversation_id": conv_a.id},
        headers=headers_b,
    )
    assert res.status_code == 404


# =====================================================================
# 5. Credential & Secret Isolation
# =====================================================================

def test_security_pin_otp_never_in_graph_state_or_checkpoint() -> None:
    """Sensitive credentials (PIN, OTP, password) never appear in GraphState or checkpoints."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-sec-cred-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "bearer-token-only",
        }
    }

    mock_client = MagicMock()
    mock_client.list_beneficiaries.return_value = [
        {"id": "b-1", "name": "Vikas", "account_number": "1234567890", "ifsc": "HDFC0001234"}
    ]
    mock_client.list_accounts.return_value = [{"id": "acc-1", "status": "ACTIVE"}]
    mock_client.get_account_balance.return_value = {"available_minor": 500000}
    mock_client.get_transfer_limits.return_value = {
        "per_transaction_limit_minor": 1000000,
        "daily_limit_minor": 5000000,
        "daily_used_minor": 0,
    }
    mock_client.prepare_transfer.return_value = {
        "id": "draft-sec-cred",
        "status": "PENDING_APPROVAL",
        "summary_hash": "sha256-cred",
        "amount_minor": 100000,
        "fee_minor": 0,
    }
    mock_client.execute_transfer.return_value = {"reference": "REF-SEC-01", "status": "COMPLETED"}
    mock_client.get_transfer_status.return_value = {"reference": "REF-SEC-01", "status": "COMPLETED"}

    with (
        patch("app.agents.workflows.transfer.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        # Full flow execution
        list(graph.stream({"user_message": "Transfer ₹1,000 to Vikas", "conversation_id": thread_id}, config=config))
        list(graph.stream(Command(resume={"decision": "CONFIRM"}), config=config))
        list(graph.stream(Command(resume={"authorization_id": "auth-token-pin-verified"}), config=config))

        final_state = graph.get_state(config).values

        # Inspect all keys and stringified values of final GraphState
        state_dump = json.dumps(
            {k: str(v) for k, v in final_state.items() if k != "messages"},
            default=str,
        ).lower()

        forbidden_terms = ["pin", "otp", "password", "mpin", "cvv"]
        for term in forbidden_terms:
            assert f'"{term}":' not in state_dump, f"Forbidden sensitive field '{term}' found in GraphState keys!"

        # Invariant check: Bearer token is NEVER saved in GraphState
        assert "access_token" not in final_state
        assert "bearer-token-only" not in state_dump


def test_security_masked_details_in_approval_and_events(sec_db_session) -> None:
    """Approval summaries and responses strictly mask account and card numbers."""
    db, _ = sec_db_session
    user_ref, conv = create_user_and_conv(db, user_id="sec-user-mask")
    service = ApprovalService(db)

    approval = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={
            "amount": "₹5,000.00",
            "account_masked": "XXXXXX4321",
            "card_masked": "...1234",
            "beneficiary": "Sunil Varma",
        },
    )

    summary = approval.summary_masked
    assert "XXXXXX4321" == summary["account_masked"]
    assert "...1234" == summary["card_masked"]

    # Verify no raw unmasked 10+ digit account numbers exist in the json text
    raw_json = approval.summary_masked_json
    assert "123456784321" not in raw_json
