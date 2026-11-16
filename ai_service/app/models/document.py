"""Document and chunk metadata models for RAG knowledge base."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Document(Base):
    """Knowledge base policy or informational document."""

    __tablename__ = "document"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    doc_group_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="UPLOADED", nullable=False
    )  # UPLOADED / PROCESSING / READY / FAILED / INACTIVE
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunks: Mapped[list[DocumentChunkMetadata]] = relationship(
        "DocumentChunkMetadata", back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("doc_group_id", "version", name="uq_document_doc_group_version"),
    )


class DocumentChunkMetadata(Base):
    """Metadata tracking document chunks indexed in the vector store."""

    __tablename__ = "document_chunk_metadata"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
