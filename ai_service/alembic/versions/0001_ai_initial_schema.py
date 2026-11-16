"""ai_initial_schema

Revision ID: 0001_ai_initial_schema
Revises: None
Create Date: 2026-11-10 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_ai_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. chat_user_reference
    op.create_table(
        "chat_user_reference",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("banking_user_id", sa.String(length=36), nullable=False),
        sa.Column("role_snapshot", sa.String(length=100), nullable=False),
        sa.Column("display_name_masked", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("banking_user_id", name="uq_chat_user_ref_banking_user_id"),
    )
    op.create_index(
        op.f("ix_chat_user_reference_banking_user_id"),
        "chat_user_reference",
        ["banking_user_id"],
        unique=True,
    )

    # 2. conversation
    op.create_table(
        "conversation",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_ref_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_ref_id"],
            ["chat_user_reference.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_user_ref_id"),
        "conversation",
        ["user_ref_id"],
        unique=False,
    )

    # 3. chat_message
    op.create_table(
        "chat_message",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content_masked", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_message_conversation_id"),
        "chat_message",
        ["conversation_id"],
        unique=False,
    )

    # 4. agent_execution
    op.create_table(
        "agent_execution",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("route", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("tool_args_masked", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_message.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_execution_conversation_id"),
        "agent_execution",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_execution_message_id"),
        "agent_execution",
        ["message_id"],
        unique=False,
    )

    # 5. pending_approval
    op.create_table(
        "pending_approval",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_type", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("summary_masked_json", sa.Text(), nullable=False),
        sa.Column("summary_hash", sa.String(length=64), nullable=False),
        sa.Column("banking_resource_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pending_approval_conversation_id"),
        "pending_approval",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pending_approval_thread_id"),
        "pending_approval",
        ["thread_id"],
        unique=False,
    )
    op.create_index(
        "ix_pending_approval_status_expires_at",
        "pending_approval",
        ["status", "expires_at"],
        unique=False,
    )

    # 6. document
    op.create_table(
        "document",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("doc_group_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'UPLOADED'"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("mime", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=64), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_group_id", "version", name="uq_document_doc_group_version"),
    )
    op.create_index(
        op.f("ix_document_doc_group_id"),
        "document",
        ["doc_group_id"],
        unique=False,
    )

    # 7. document_chunk_metadata
    op.create_table(
        "document_chunk_metadata",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=255), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_chunk_metadata_document_id"),
        "document_chunk_metadata",
        ["document_id"],
        unique=False,
    )

    # 8. workflow_checkpoint_metadata
    op.create_table(
        "workflow_checkpoint_metadata",
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("last_node", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_index(
        op.f("ix_workflow_checkpoint_metadata_conversation_id"),
        "workflow_checkpoint_metadata",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_checkpoint_metadata_conversation_id"),
        table_name="workflow_checkpoint_metadata",
    )
    op.drop_table("workflow_checkpoint_metadata")

    op.drop_index(
        op.f("ix_document_chunk_metadata_document_id"),
        table_name="document_chunk_metadata",
    )
    op.drop_table("document_chunk_metadata")

    op.drop_index(op.f("ix_document_doc_group_id"), table_name="document")
    op.drop_table("document")

    op.drop_index("ix_pending_approval_status_expires_at", table_name="pending_approval")
    op.drop_index(op.f("ix_pending_approval_thread_id"), table_name="pending_approval")
    op.drop_index(op.f("ix_pending_approval_conversation_id"), table_name="pending_approval")
    op.drop_table("pending_approval")

    op.drop_index(op.f("ix_agent_execution_message_id"), table_name="agent_execution")
    op.drop_index(op.f("ix_agent_execution_conversation_id"), table_name="agent_execution")
    op.drop_table("agent_execution")

    op.drop_index(op.f("ix_chat_message_conversation_id"), table_name="chat_message")
    op.drop_table("chat_message")

    op.drop_index(op.f("ix_conversation_user_ref_id"), table_name="conversation")
    op.drop_table("conversation")

    op.drop_index(
        op.f("ix_chat_user_reference_banking_user_id"),
        table_name="chat_user_reference",
    )
    op.drop_table("chat_user_reference")
