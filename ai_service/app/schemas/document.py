"""Pydantic schemas for RAG document management."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChunkMeta(BaseModel):
    """Metadata for an indexed document chunk."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_index: int
    page: int | None = None
    section: str | None = None
    vector_id: str | None = None
    token_count: int | None = None


class DocumentUploadResponse(BaseModel):
    """Response returned upon uploading a document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    version: str
    status: str
    uploaded_at: datetime


class DocumentListItem(BaseModel):
    """Document summary item for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    version: str
    doc_group_id: str
    status: str
    active: bool
    size_bytes: int | None = None
    uploaded_at: datetime
    uploaded_by: str | None = None


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class DocumentDetailResponse(BaseModel):
    """Detailed document representation including chunk metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    version: str
    doc_group_id: str
    status: str
    active: bool
    sha256: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    uploaded_by: str | None = None
    uploaded_at: datetime
    error: str | None = None
    chunks: list[ChunkMeta] = Field(default_factory=list)


class DocumentUpdateRequest(BaseModel):
    """Request payload for updating document properties."""

    active: bool | None = None


class DocumentReprocessResponse(BaseModel):
    """Response returned when triggering re-ingestion."""

    document_id: str
    status: str
    message: str
