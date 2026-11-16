"""Document repository for database operations on Document and chunk metadata."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.document import Document, DocumentChunkMetadata


class DocumentRepository:
    """Repository handling database operations for Document and DocumentChunkMetadata entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        category: str,
        version: str,
        doc_group_id: str,
        sha256: str | None = None,
        mime: str | None = None,
        size_bytes: int | None = None,
        uploaded_by: str | None = None,
        id: str | None = None,
    ) -> Document:
        """Create and persist a new Document record."""
        doc = Document(
            id=id or str(uuid.uuid4()),
            name=name,
            category=category,
            version=version,
            doc_group_id=doc_group_id,
            status="UPLOADED",
            active=True,
            sha256=sha256,
            mime=mime,
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(timezone.utc),
        )
        self.session.add(doc)
        self.session.flush()
        self.session.refresh(doc)
        return doc

    def get_by_id(self, document_id: str) -> Document | None:
        """Retrieve a document by ID including its chunk metadata."""
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_group_and_version(self, doc_group_id: str, version: str) -> Document | None:
        """Retrieve a document by doc_group_id and version string."""
        stmt = select(Document).where(
            Document.doc_group_id == doc_group_id,
            Document.version == version,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_sha256(self, sha256: str) -> Document | None:
        """Retrieve a document by its SHA-256 hash (deduplication check)."""
        stmt = select(Document).where(Document.sha256 == sha256)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(
        self,
        category: str | None = None,
        active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Document], int]:
        """List documents with optional category and active filtering, with pagination."""
        stmt = select(Document)
        count_stmt = select(func.count(Document.id))

        if category is not None:
            stmt = stmt.where(Document.category == category)
            count_stmt = count_stmt.where(Document.category == category)
        if active is not None:
            stmt = stmt.where(Document.active == active)
            count_stmt = count_stmt.where(Document.active == active)

        total = self.session.execute(count_stmt).scalar_one()

        offset = max(0, (page - 1) * page_size)
        stmt = stmt.order_by(Document.uploaded_at.desc()).offset(offset).limit(page_size)
        items = list(self.session.execute(stmt).scalars().all())
        return items, total

    def update_status(self, document_id: str, status: str, error: str | None = None) -> None:
        """Update the processing status and optional error/warning message."""
        doc = self.get_by_id(document_id)
        if doc:
            doc.status = status
            doc.error = error
            self.session.add(doc)
            self.session.flush()

    def deactivate_older_versions(self, doc_group_id: str, except_id: str) -> None:
        """Set active=False for all documents in a group except the specified ID."""
        stmt = (
            update(Document)
            .where(
                Document.doc_group_id == doc_group_id,
                Document.id != except_id,
            )
            .values(active=False)
        )
        self.session.execute(stmt)
        self.session.flush()

    def deactivate(self, document_id: str) -> None:
        """Set active=False for a single document."""
        doc = self.get_by_id(document_id)
        if doc:
            doc.active = False
            self.session.add(doc)
            self.session.flush()

    def get_versions(self, doc_group_id: str) -> list[Document]:
        """Retrieve all versions in a document group ordered by uploaded_at desc."""
        stmt = (
            select(Document)
            .where(Document.doc_group_id == doc_group_id)
            .order_by(Document.uploaded_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def delete(self, document_id: str) -> None:
        """Delete a document record from the database (chunks cascade delete)."""
        doc = self.get_by_id(document_id)
        if doc:
            self.session.delete(doc)
            self.session.flush()
