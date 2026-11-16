"""Unit tests for AI service database models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.agent import AgentExecution
from app.models.approval import PendingApproval
from app.models.chat import ChatMessage, ChatUserReference, Conversation
from app.models.checkpoint import WorkflowCheckpointMetadata
from app.models.document import Document, DocumentChunkMetadata


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_chat_models_and_relationships(db_session: Session) -> None:
    user_ref = ChatUserReference(
        banking_user_id="user-123",
        role_snapshot="CUSTOMER",
        display_name_masked="J*** D***",
    )
    db_session.add(user_ref)
    db_session.commit()

    conv = Conversation(
        user_ref_id=user_ref.id,
        title="Check Balance",
    )
    db_session.add(conv)
    db_session.commit()

    msg1 = ChatMessage(
        conversation_id=conv.id,
        role="user",
        content_masked="What is my account balance?",
    )
    msg2 = ChatMessage(
        conversation_id=conv.id,
        role="assistant",
        content_masked="Your balance is 5,000 INR.",
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()

    assert len(user_ref.conversations) == 1
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"


def test_approval_and_execution_models(db_session: Session) -> None:
    user_ref = ChatUserReference(
        banking_user_id="user-456",
        role_snapshot="CUSTOMER",
        display_name_masked="A*** B***",
    )
    db_session.add(user_ref)
    db_session.commit()

    conv = Conversation(user_ref_id=user_ref.id)
    db_session.add(conv)
    db_session.commit()

    now = datetime.now(timezone.utc)
    approval = PendingApproval(
        conversation_id=conv.id,
        thread_id="th-1",
        workflow_type="TRANSFER",
        risk_level="HIGH",
        summary_masked_json='{"amount": 10000}',
        summary_hash="sha256-hash",
        banking_resource_id="txn-999",
        expires_at=now,
    )
    execution = AgentExecution(
        conversation_id=conv.id,
        node="transfer_node",
        status="SUCCESS",
        latency_ms=120,
    )
    checkpoint = WorkflowCheckpointMetadata(
        thread_id="th-1",
        conversation_id=conv.id,
        checkpoint_id="cp-1",
        last_node="transfer_node",
    )
    db_session.add_all([approval, execution, checkpoint])
    db_session.commit()

    assert len(conv.pending_approvals) == 1
    assert len(conv.executions) == 1
    assert len(conv.checkpoints) == 1


def test_document_and_chunks(db_session: Session) -> None:
    doc = Document(
        name="transfer_policy.pdf",
        category="POLICY",
        version="1.0",
        doc_group_id="policy-transfers",
        size_bytes=1024,
    )
    db_session.add(doc)
    db_session.commit()

    chunk1 = DocumentChunkMetadata(
        document_id=doc.id,
        chunk_index=0,
        page=1,
        token_count=150,
    )
    chunk2 = DocumentChunkMetadata(
        document_id=doc.id,
        chunk_index=1,
        page=2,
        token_count=200,
    )
    db_session.add_all([chunk1, chunk2])
    db_session.commit()

    assert len(doc.chunks) == 2
    assert doc.chunks[0].chunk_index == 0
