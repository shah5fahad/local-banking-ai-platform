"""Comprehensive unit and integration tests for Phase 5 task T5.6:
Expiry sweeper, cleanup, checkpoint pruning, and superseding rules.

Covers:
1. Superseding Rules:
   - Creating a new approval supersedes prior active approvals in that conversation
   - Superseding cancels existing Banking API drafts for transfers
   - Superseding is isolated by workflow type and conversation
   - Superseded approvals reject decide/resume operations with 409 Conflict
   - get_active_approval_for_conversation returns current active approval or auto-expires
2. Expiry Sweeper:
   - Sweeping expired approvals (expires_at <= now())
   - Marking EXPIRED, setting decided_at
   - Banking API draft cancellation on expiry for transfer workflows
   - Resuming/closing interrupted LangGraph threads
   - Graceful error handling if banking service is unreachable
3. Checkpoint Pruning:
   - Retention threshold filtering (older_than_days)
   - Pruning WorkflowCheckpointMetadata rows
   - Pruning SQLite checkpointer tables (checkpoints, checkpoint_blobs, checkpoint_writes)
   - Pruning in-memory checkpointer storage
4. Periodic Sweeper Task:
   - Async background sweeper execution and graceful stop event termination
5. REST API Endpoints:
   - GET /chat/approvals/active
   - POST /chat/approvals/sweep
   - POST /chat/checkpoints/prune
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.errors import ConflictError
from app.db.base import Base
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.main import create_app
from app.models.approval import ApprovalStatus, PendingApproval, RiskLevel, WorkflowType
from app.models.chat import ChatUserReference, Conversation
from app.models.checkpoint import WorkflowCheckpointMetadata
from app.services.approval_service import ApprovalService
from app.services.expiry_sweeper import ExpirySweeperService, run_periodic_sweeper


@pytest.fixture
def test_db_session():
    """Create in-memory SQLite database session for unit tests."""
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


def make_test_token(user_id: str = "test-user-sweeper", roles: list[str] | None = None) -> str:
    """Generate signed JWT token for test user."""
    settings = get_settings()
    payload = {
        "sub": user_id,
        "roles": roles or ["CUSTOMER"],
        "sid": "session-sweeper-test",
        "exp": 9999999999,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def setup_user_and_conversation(
    db: Session,
    user_id: str = "user-sweeper-1",
    conv_id: str | None = None,
) -> tuple[ChatUserReference, Conversation]:
    """Helper to seed user reference and conversation."""
    user_ref = ChatUserReference(
        banking_user_id=user_id,
        role_snapshot="CUSTOMER",
        display_name_masked="Sweeper Test User",
    )
    db.add(user_ref)
    db.commit()

    conv = Conversation(
        id=conv_id,
        user_ref_id=user_ref.id,
        title="Sweeper Test Conversation",
    )
    db.add(conv)
    db.commit()
    return user_ref, conv


# =====================================================================
# 1. Superseding Rules
# =====================================================================

def test_create_approval_supersedes_prior_active_approval(test_db_session) -> None:
    """Creating a new approval for the same conversation and workflow supersedes the prior one."""
    db, _ = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="user-super-1")
    service = ApprovalService(db)

    # 1. Create first transfer approval
    app1 = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}-1",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹5,000", "to": "Alice"},
    )
    assert app1.status == ApprovalStatus.PENDING.value

    # 2. Create second transfer approval for same conversation
    app2 = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}-2",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹10,000", "to": "Bob"},
    )

    # Refresh app1
    db.refresh(app1)
    assert app1.status == ApprovalStatus.SUPERSEDED.value
    assert app1.decided_at is not None
    assert app2.status == ApprovalStatus.PENDING.value

    # Checkpoint metadata for app1 should be marked SUPERSEDED
    chk1 = db.get(WorkflowCheckpointMetadata, app1.thread_id)
    assert chk1 is not None
    assert chk1.status == "SUPERSEDED"

    # Checkpoint metadata for app2 should be ACTIVE
    chk2 = db.get(WorkflowCheckpointMetadata, app2.thread_id)
    assert chk2 is not None
    assert chk2.status == "ACTIVE"


def test_superseding_cancels_banking_draft(test_db_session) -> None:
    """Superseding a transfer approval automatically calls BankingClient.cancel_transfer."""
    db, _ = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="user-super-2")
    service = ApprovalService(db)

    # First approval has a banking draft id
    app1 = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}-1",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-to-cancel-123",
        summary_masked={"amount": "₹2,000"},
    )

    with patch("app.services.approval_service.BankingClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Create second approval
        app2 = service.create_approval(
            conversation_id=conv.id,
            thread_id=f"thread-{conv.id}-2",
            workflow_type=WorkflowType.TRANSFER.value,
            summary_masked={"amount": "₹4,000"},
            raw_token="mock-jwt-token",
        )

        mock_client.cancel_transfer.assert_called_once_with("draft-to-cancel-123")

    db.refresh(app1)
    assert app1.status == ApprovalStatus.SUPERSEDED.value
    assert app2.status == ApprovalStatus.PENDING.value


def test_superseding_is_isolated_by_workflow_type(test_db_session) -> None:
    """A transfer approval does not supersede an active loan approval in the same conversation."""
    db, _ = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="user-super-3")
    service = ApprovalService(db)

    loan_app = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}-loan",
        workflow_type=WorkflowType.LOAN.value,
        summary_masked={"amount": "₹5,00,000"},
    )

    transfer_app = service.create_approval(
        conversation_id=conv.id,
        thread_id=f"thread-{conv.id}-transfer",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )

    db.refresh(loan_app)
    assert loan_app.status == ApprovalStatus.PENDING.value
    assert transfer_app.status == ApprovalStatus.PENDING.value


def test_superseding_is_isolated_by_conversation(test_db_session) -> None:
    """An approval in conversation A does not supersede an approval in conversation B."""
    db, _ = test_db_session
    user_ref, conv_a = setup_user_and_conversation(db, user_id="user-super-4")
    conv_b = Conversation(id="conv-b-id", user_ref_id=user_ref.id, title="Conv B")
    db.add(conv_b)
    db.commit()

    service = ApprovalService(db)
    app_a = service.create_approval(
        conversation_id=conv_a.id,
        thread_id="thread-a",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )
    app_b = service.create_approval(
        conversation_id=conv_b.id,
        thread_id="thread-b",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹2,000"},
    )

    db.refresh(app_a)
    db.refresh(app_b)
    assert app_a.status == ApprovalStatus.PENDING.value
    assert app_b.status == ApprovalStatus.PENDING.value


def test_superseded_approval_rejects_decision_and_resume(test_db_session) -> None:
    """Operations on superseded approvals raise ConflictError."""
    db, _ = test_db_session
    user_ref, conv = setup_user_and_conversation(db, user_id="user-super-5")
    service = ApprovalService(db)

    app1 = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-1",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹500"},
    )
    # Supersede app1 by creating app2
    service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-2",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )
    db.refresh(app1)
    assert app1.status == ApprovalStatus.SUPERSEDED.value

    # Attempt decision on app1
    with pytest.raises(ConflictError) as exc_decision:
        service.decide_approval(
            approval_id=app1.id,
            decision="CONFIRM",
            banking_user_id=user_ref.banking_user_id,
        )
    assert "superseded" in str(exc_decision.value).lower()

    # Attempt resume on app1
    with pytest.raises(ConflictError) as exc_resume:
        service.resume_approval(
            approval_id=app1.id,
            authorization_id="auth-xyz",
            banking_user_id=user_ref.banking_user_id,
            raw_token="dummy",
        )
    assert "superseded" in str(exc_resume.value).lower()


def test_get_active_approval_for_conversation(test_db_session) -> None:
    """get_active_approval_for_conversation retrieves the current active approval and detects expiry."""
    db, _ = test_db_session
    user_ref, conv = setup_user_and_conversation(db, user_id="user-super-6")
    service = ApprovalService(db)

    # None initially
    assert service.get_active_approval_for_conversation(conv.id) is None

    # Create active approval
    app = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-act-1",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹1,000"},
    )
    active = service.get_active_approval_for_conversation(conv.id)
    assert active is not None
    assert active.id == app.id

    # If it is expired, returns None and updates status
    app.expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db.commit()

    active_after_expiry = service.get_active_approval_for_conversation(conv.id)
    assert active_after_expiry is None
    db.refresh(app)
    assert app.status == ApprovalStatus.EXPIRED.value


# =====================================================================
# 2. Expiry Sweeper
# =====================================================================

def test_sweep_expired_approvals_cancels_drafts_and_updates_status(test_db_session) -> None:
    """Sweeper identifies expired approvals, cancels transfer drafts, marks EXPIRED, and unblocks threads."""
    db, _ = test_db_session
    user_ref, conv = setup_user_and_conversation(db, user_id="user-sweep-1")
    service = ApprovalService(db)
    sweeper = ExpirySweeperService(db)

    now = datetime.now(UTC)

    # 1. Expired transfer draft (should be cancelled and marked EXPIRED)
    app_expired_transfer = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-exp-transfer",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-sweep-999",
        summary_masked={"amount": "₹5,000"},
        auto_supersede=False,
    )
    app_expired_transfer.expires_at = now - timedelta(seconds=60)

    # 2. Unexpired transfer draft (should remain PENDING)
    app_active_transfer = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-active-transfer",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-active-001",
        summary_masked={"amount": "₹2,000"},
        auto_supersede=False,
    )
    app_active_transfer.expires_at = now + timedelta(seconds=300)

    # 3. Expired card payment (should be marked EXPIRED without calling draft cancel)
    app_expired_card = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-exp-card",
        workflow_type=WorkflowType.CARD_PAYMENT.value,
        summary_masked={"card": "Visa ...1234"},
        auto_supersede=False,
    )
    app_expired_card.expires_at = now - timedelta(seconds=120)

    db.commit()

    with (
        patch("app.services.expiry_sweeper.BankingClient") as mock_client_cls,
        patch("app.agents.graph.resume_graph") as mock_resume,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        results = sweeper.sweep_expired_approvals(raw_token="test-jwt")

        assert len(results) == 2
        swept_ids = [r["approval_id"] for r in results]
        assert app_expired_transfer.id in swept_ids
        assert app_expired_card.id in swept_ids
        assert app_active_transfer.id not in swept_ids

        # BankingClient.cancel_transfer called for transfer draft
        mock_client.cancel_transfer.assert_called_once_with("draft-sweep-999")

        # resume_graph called to unstick waiting interrupts
        assert mock_resume.call_count == 2

    db.refresh(app_expired_transfer)
    db.refresh(app_active_transfer)
    db.refresh(app_expired_card)

    assert app_expired_transfer.status == ApprovalStatus.EXPIRED.value
    assert app_expired_transfer.decided_at is not None
    assert app_expired_card.status == ApprovalStatus.EXPIRED.value
    assert app_active_transfer.status == ApprovalStatus.PENDING.value

    # Checkpoint metadata should be marked EXPIRED
    chk_exp = db.get(WorkflowCheckpointMetadata, app_expired_transfer.thread_id)
    assert chk_exp is not None
    assert chk_exp.status == "EXPIRED"


def test_sweeper_handles_banking_failure_gracefully(test_db_session) -> None:
    """If the banking API throws an error when cancelling a draft, the sweeper still marks EXPIRED."""
    db, _ = test_db_session
    user_ref, conv = setup_user_and_conversation(db, user_id="user-sweep-fail")
    service = ApprovalService(db)
    sweeper = ExpirySweeperService(db)

    app = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-sweep-fail",
        workflow_type=WorkflowType.TRANSFER.value,
        banking_resource_id="draft-fail-555",
        summary_masked={"amount": "₹3,000"},
    )
    app.expires_at = datetime.now(UTC) - timedelta(seconds=30)
    db.commit()

    with (
        patch("app.services.expiry_sweeper.BankingClient") as mock_client_cls,
        patch("app.agents.graph.resume_graph"),
    ):
        mock_client = MagicMock()
        mock_client.cancel_transfer.side_effect = RuntimeError("Banking service 503")
        mock_client_cls.return_value = mock_client

        results = sweeper.sweep_expired_approvals()

        assert len(results) == 1
        assert results[0]["approval_id"] == app.id
        assert results[0]["cancelled_draft"] is False

    db.refresh(app)
    assert app.status == ApprovalStatus.EXPIRED.value


# =====================================================================
# 3. Checkpoint Pruning
# =====================================================================

def test_prune_checkpoints_metadata(test_db_session) -> None:
    """Stale/terminal WorkflowCheckpointMetadata records older than cutoff are pruned."""
    db, _ = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="user-prune-1")
    sweeper = ExpirySweeperService(db)

    now = datetime.now(UTC)
    old_time = now - timedelta(days=10)
    recent_time = now - timedelta(days=2)

    # 1. Old expired metadata (should be pruned)
    old_meta = WorkflowCheckpointMetadata(
        thread_id="thread-old-1",
        conversation_id=conv.id,
        last_node="approval_gate",
        status="EXPIRED",
        expires_at=old_time,
        created_at=old_time,
    )
    db.add(old_meta)

    # 2. Old executed metadata (should be pruned)
    old_exec_meta = WorkflowCheckpointMetadata(
        thread_id="thread-old-2",
        conversation_id=conv.id,
        last_node="execute",
        status="EXECUTED",
        created_at=old_time,
    )
    db.add(old_exec_meta)

    # 3. Recent active metadata (should NOT be pruned)
    recent_meta = WorkflowCheckpointMetadata(
        thread_id="thread-recent-1",
        conversation_id=conv.id,
        last_node="approval_gate",
        status="ACTIVE",
        expires_at=now + timedelta(minutes=5),
        created_at=recent_time,
    )
    db.add(recent_meta)
    db.commit()

    stats = sweeper.prune_checkpoints(older_than_days=7)
    assert stats["pruned_metadata"] == 2

    assert db.get(WorkflowCheckpointMetadata, "thread-old-1") is None
    assert db.get(WorkflowCheckpointMetadata, "thread-old-2") is None
    assert db.get(WorkflowCheckpointMetadata, "thread-recent-1") is not None


def test_prune_checkpoints_sqlite_tables(test_db_session) -> None:
    """prune_checkpoints deletes records from checkpoints, checkpoint_blobs, and checkpoint_writes."""
    db, _ = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="user-prune-sqlite")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        sqlite_file = tf.name

    try:
        # Create SQLite checkpointer schema
        conn = sqlite3.connect(sqlite_file)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE checkpoints (
                thread_id TEXT,
                checkpoint_id TEXT,
                parent_id TEXT,
                metadata BLOB
            )
        """)
        cur.execute("""
            CREATE TABLE checkpoint_blobs (
                thread_id TEXT,
                channel TEXT,
                blob BLOB
            )
        """)
        cur.execute("""
            CREATE TABLE checkpoint_writes (
                thread_id TEXT,
                checkpoint_id TEXT,
                blob BLOB
            )
        """)

        # Insert rows for 'thread-stale' and 'thread-keep'
        cur.execute("INSERT INTO checkpoints VALUES ('thread-stale', 'chk-1', NULL, 'data')")
        cur.execute("INSERT INTO checkpoints VALUES ('thread-keep', 'chk-2', NULL, 'data')")
        cur.execute("INSERT INTO checkpoint_blobs VALUES ('thread-stale', 'state', 'blob1')")
        cur.execute("INSERT INTO checkpoint_blobs VALUES ('thread-keep', 'state', 'blob2')")
        cur.execute("INSERT INTO checkpoint_writes VALUES ('thread-stale', 'chk-1', 'write1')")
        cur.execute("INSERT INTO checkpoint_writes VALUES ('thread-keep', 'chk-2', 'write2')")
        conn.commit()
        conn.close()

        # Add metadata for thread-stale in AI DB
        old_time = datetime.now(UTC) - timedelta(days=14)
        stale_meta = WorkflowCheckpointMetadata(
            thread_id="thread-stale",
            conversation_id=conv.id,
            status="EXPIRED",
            created_at=old_time,
            expires_at=old_time,
        )
        db.add(stale_meta)
        db.commit()

        sweeper = ExpirySweeperService(db)
        stats = sweeper.prune_checkpoints(older_than_days=7, db_path=sqlite_file)

        assert stats["pruned_metadata"] == 1
        assert stats["pruned_checkpoints"] == 1
        assert stats["pruned_blobs"] == 1
        assert stats["pruned_writes"] == 1

        # Verify SQLite DB
        conn = sqlite3.connect(sqlite_file)
        cur = conn.cursor()
        remaining_chks = cur.execute("SELECT thread_id FROM checkpoints").fetchall()
        remaining_blobs = cur.execute("SELECT thread_id FROM checkpoint_blobs").fetchall()
        remaining_writes = cur.execute("SELECT thread_id FROM checkpoint_writes").fetchall()
        conn.close()

        assert remaining_chks == [("thread-keep",)]
        assert remaining_blobs == [("thread-keep",)]
        assert remaining_writes == [("thread-keep",)]

    finally:
        if os.path.exists(sqlite_file):
            os.remove(sqlite_file)


# =====================================================================
# 4. Periodic Sweeper Task
# =====================================================================

@pytest.mark.asyncio
async def test_run_periodic_sweeper_cycle(test_db_session) -> None:
    """Periodic sweeper loop runs a sweep cycle and terminates cleanly on stop_event."""
    db, session_factory = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="user-periodic")
    service = ApprovalService(db)

    # Seed an expired approval
    app = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-periodic-1",
        workflow_type=WorkflowType.CARD_PAYMENT.value,
        summary_masked={"card": "Mastercard ...5678"},
    )
    app.expires_at = datetime.now(UTC) - timedelta(seconds=15)
    db.commit()

    settings = get_settings().model_copy(update={"sweeper_interval_seconds": 1})
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        run_periodic_sweeper(session_factory, settings, stop_event=stop_event)
    )

    # Allow one cycle to run
    await asyncio.sleep(0.1)
    stop_event.set()
    await task

    db.refresh(app)
    assert app.status == ApprovalStatus.EXPIRED.value


# =====================================================================
# 5. REST API Endpoints
# =====================================================================

def test_api_get_active_approval(test_db_session) -> None:
    """GET /chat/approvals/active returns current active approval or null."""
    db, session_factory = test_db_session
    user_ref, conv = setup_user_and_conversation(db, user_id="api-active-user")
    service = ApprovalService(db)

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token = make_test_token(user_id="api-active-user")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. No active approval -> returns null / None
    res = client.get(f"/api/v1/chat/approvals/active?conversation_id={conv.id}", headers=headers)
    assert res.status_code == 200
    assert res.json() is None

    # 2. Create active approval -> returns approval
    app = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-api-active",
        workflow_type=WorkflowType.TRANSFER.value,
        summary_masked={"amount": "₹3,500"},
    )

    res = client.get(f"/api/v1/chat/approvals/active?conversation_id={conv.id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["approval_id"] == app.id
    assert data["status"] == "PENDING"
    assert data["summary"]["amount"] == "₹3,500"


def test_api_sweep_approvals_endpoint(test_db_session) -> None:
    """POST /chat/approvals/sweep manually triggers sweep and returns swept details."""
    db, session_factory = test_db_session
    user_ref, conv = setup_user_and_conversation(db, user_id="api-sweep-user")
    service = ApprovalService(db)

    # Create expired approval
    app = service.create_approval(
        conversation_id=conv.id,
        thread_id="thread-api-sweep",
        workflow_type=WorkflowType.CARD_PAYMENT.value,
        summary_masked={"amount": "₹1,200"},
    )
    app.expires_at = datetime.now(UTC) - timedelta(seconds=20)
    db.commit()

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token = make_test_token(user_id="api-sweep-user")
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.agents.graph.resume_graph"):
        res = client.post("/api/v1/chat/approvals/sweep", headers=headers)

    assert res.status_code == 200
    data = res.json()
    assert data["swept_count"] == 1
    assert app.id in data["swept_approvals"]

    db.refresh(app)
    assert app.status == ApprovalStatus.EXPIRED.value


def test_api_prune_checkpoints_endpoint(test_db_session) -> None:
    """POST /chat/checkpoints/prune prunes stale metadata and returns statistics."""
    db, session_factory = test_db_session
    _, conv = setup_user_and_conversation(db, user_id="api-prune-user")

    # Add old terminal metadata
    old_time = datetime.now(UTC) - timedelta(days=12)
    stale_meta = WorkflowCheckpointMetadata(
        thread_id="thread-api-stale",
        conversation_id=conv.id,
        status="EXPIRED",
        created_at=old_time,
        expires_at=old_time,
    )
    db.add(stale_meta)
    db.commit()

    app_instance = create_app()
    app_instance.dependency_overrides[get_db] = lambda: db
    app_instance.dependency_overrides[get_session_factory] = lambda: session_factory

    client = TestClient(app_instance)
    token = make_test_token(user_id="api-prune-user")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/api/v1/chat/checkpoints/prune",
        json={"older_than_days": 7},
        headers=headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["pruned_metadata_count"] == 1
    assert "Successfully pruned" in data["message"]

    assert db.get(WorkflowCheckpointMetadata, "thread-api-stale") is None
