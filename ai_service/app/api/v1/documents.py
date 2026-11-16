"""FastAPI document management endpoints for knowledge base administration."""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import AISettings, get_settings
from app.core.errors import AIError, ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import decode_banking_jwt, extract_roles, extract_user_id
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.integrations.vectorstore_factory import get_vectorstore
from app.rag.ingestion import run_ingestion_pipeline
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentReprocessResponse,
    DocumentUpdateRequest,
    DocumentUploadResponse,
)

logger = logging.getLogger(__name__)

bearer_auth = HTTPBearer(auto_error=False)


def require_admin_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    settings: AISettings = Depends(get_settings),
) -> str:
    """Authorize admin access via X-Service-Key header or JWT with ADMIN role."""
    if x_service_key and x_service_key == settings.service_key:
        return "service:admin"

    if credentials:
        payload = decode_banking_jwt(credentials.credentials, settings)
        roles = [r.upper() for r in extract_roles(payload)]
        if "ADMIN" in roles or payload.get("is_admin") is True:
            return extract_user_id(payload)
        raise ForbiddenError("Admin access required")

    raise UnauthorizedError("Authentication required (provide valid X-Service-Key or Admin JWT)")


AdminUser = Annotated[str, Depends(require_admin_access)]
DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[AISettings, Depends(get_settings)]

router = APIRouter(prefix="/documents", tags=["documents"])


def sanitize_filename(filename: str) -> str:
    """Sanitize raw filename to prevent directory traversal and illegal characters."""
    base = Path(filename).name
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    return sanitized or "document.bin"


def _safe_delete_vectors(settings: AISettings, document_id: str) -> None:
    """Safely delete vectors from vector store collection by document_id metadata filter."""
    try:
        vs = get_vectorstore(settings)
        if hasattr(vs, "_collection") and hasattr(vs._collection, "delete"):
            vs._collection.delete(where={"document_id": document_id})
        elif hasattr(vs, "delete"):
            try:
                vs.delete(where={"document_id": document_id})
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Could not delete vectors for document %s: %s", document_id, exc)


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload and ingest a new document",
)
@router.post(
    "/",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
async def upload_document(
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    admin_user: AdminUser,
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form(...),
    version: str = Form(...),
    doc_group_id: str | None = Form(None),
) -> DocumentUploadResponse:
    """Upload raw policy/knowledge document and queue asynchronous ingestion."""
    # Read file content
    content = await file.read()
    size_bytes = len(content)

    # Size check
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise AIError(
            error_code="FILE_TOO_LARGE",
            message=f"File exceeds maximum upload size of {settings.max_upload_size_mb} MB",
            http_status=400,
        )
    if size_bytes == 0:
        raise AIError(
            error_code="EMPTY_FILE",
            message="Uploaded file is empty",
            http_status=400,
        )

    # Extension check
    raw_filename = file.filename or name or "document.bin"
    safe_name = sanitize_filename(raw_filename)
    ext = Path(safe_name).suffix.lower()
    if ext not in {".pdf", ".docx", ".txt"}:
        raise AIError(
            error_code="UNSUPPORTED_MEDIA_TYPE",
            message=f"Unsupported file extension '{ext}'. Allowed: .pdf, .docx, .txt",
            http_status=400,
        )

    # Deduplication checks
    sha256 = hashlib.sha256(content).hexdigest()
    repo = DocumentRepository(db)
    existing_doc = repo.get_by_sha256(sha256)
    if existing_doc:
        raise ConflictError(f"Document with identical content already exists (id={existing_doc.id})")

    effective_group_id = doc_group_id or str(uuid.uuid4())
    existing_ver = repo.get_by_group_and_version(effective_group_id, version)
    if existing_ver:
        raise ConflictError(
            f"Document version '{version}' for group '{effective_group_id}' already exists"
        )

    # Save to disk in data/uploads/<uuid>/<safe_filename>
    doc_id = str(uuid.uuid4())
    upload_path = Path(settings.upload_dir) / doc_id
    upload_path.mkdir(parents=True, exist_ok=True)
    target_file = upload_path / safe_name
    with open(target_file, "wb") as f:
        f.write(content)

    # Persist document record
    doc = repo.create(
        id=doc_id,
        name=name,
        category=category,
        version=version,
        doc_group_id=effective_group_id,
        sha256=sha256,
        mime=file.content_type,
        size_bytes=size_bytes,
        uploaded_by=admin_user,
    )
    db.commit()
    db.refresh(doc)

    # Trigger background ingestion
    background_tasks.add_task(
        run_ingestion_pipeline,
        doc.id,
        str(target_file),
        settings,
        get_session_factory(),
    )

    return DocumentUploadResponse.model_validate(doc)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
)
@router.get(
    "/",
    response_model=DocumentListResponse,
    include_in_schema=False,
)
def list_documents(
    db: DbSession,
    _admin_user: AdminUser,
    category: str | None = Query(None, description="Filter by category"),
    active: bool | None = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> DocumentListResponse:
    """List documents with optional category and active status filtering."""
    repo = DocumentRepository(db)
    items, total = repo.list_all(
        category=category,
        active=active,
        page=page,
        page_size=page_size,
    )
    return DocumentListResponse(
        items=[DocumentListItem.model_validate(it) for it in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get document details",
)
def get_document(
    document_id: str,
    db: DbSession,
    _admin_user: AdminUser,
) -> DocumentDetailResponse:
    """Retrieve full details of a document including indexed chunk metadata."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)
    return DocumentDetailResponse.model_validate(doc)


@router.patch(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Update document active state",
)
def update_document(
    document_id: str,
    body: DocumentUpdateRequest,
    db: DbSession,
    _admin_user: AdminUser,
) -> DocumentDetailResponse:
    """Update active status. If activating, deactivates older versions in the same group."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)

    if body.active is not None:
        doc.active = body.active
        if body.active:
            repo.deactivate_older_versions(doc_group_id=doc.doc_group_id, except_id=doc.id)
        db.commit()
        db.refresh(doc)

    return DocumentDetailResponse.model_validate(doc)


@router.post(
    "/{document_id}/activate",
    response_model=DocumentDetailResponse,
    summary="Activate a document and deactivate older versions in group",
)
def activate_document(
    document_id: str,
    db: DbSession,
    _admin_user: AdminUser,
) -> DocumentDetailResponse:
    """Explicitly activate document and deactivate previous versions."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)

    doc.active = True
    repo.deactivate_older_versions(doc_group_id=doc.doc_group_id, except_id=doc.id)
    db.commit()
    db.refresh(doc)
    return DocumentDetailResponse.model_validate(doc)


@router.post(
    "/{document_id}/deactivate",
    response_model=DocumentDetailResponse,
    summary="Deactivate a document",
)
def deactivate_document(
    document_id: str,
    db: DbSession,
    _admin_user: AdminUser,
) -> DocumentDetailResponse:
    """Explicitly deactivate document so it is excluded from RAG retrieval."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)

    doc.active = False
    db.commit()
    db.refresh(doc)
    return DocumentDetailResponse.model_validate(doc)


@router.get(
    "/{document_id}/versions",
    response_model=list[DocumentListItem],
    summary="List all versions in document group",
)
def get_document_versions(
    document_id: str,
    db: DbSession,
    _admin_user: AdminUser,
) -> list[DocumentListItem]:
    """Retrieve all versions belonging to the same document group."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)

    versions = repo.get_versions(doc.doc_group_id)
    return [DocumentListItem.model_validate(v) for v in versions]



@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentReprocessResponse,
    summary="Reprocess an existing document",
)
def reprocess_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    _admin_user: AdminUser,
) -> DocumentReprocessResponse:
    """Delete existing indexed vectors and re-run the ingestion pipeline."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)

    # 1. Delete vector store chunks
    _safe_delete_vectors(settings, document_id)

    # 2. Clear existing chunk metadata rows
    doc.chunks.clear()
    doc.status = "UPLOADED"
    doc.error = None
    db.commit()
    db.refresh(doc)

    # 3. Locate raw file on disk
    upload_dir = Path(settings.upload_dir) / document_id
    raw_file: Path | None = None
    if upload_dir.exists():
        for f in upload_dir.iterdir():
            if f.is_file():
                raw_file = f
                break

    if not raw_file or not raw_file.exists():
        raise NotFoundError("Document source file on disk", document_id)

    # 4. Trigger ingestion background task
    background_tasks.add_task(
        run_ingestion_pipeline,
        doc.id,
        str(raw_file),
        settings,
        get_session_factory(),
    )

    return DocumentReprocessResponse(
        document_id=doc.id,
        status=doc.status,
        message="Document re-ingestion started",
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document, chunks, vectors, and files",
)
def delete_document(
    document_id: str,
    db: DbSession,
    settings: AppSettings,
    _admin_user: AdminUser,
) -> Response:
    """Delete document from vector store, disk storage, and database."""
    repo = DocumentRepository(db)
    doc = repo.get_by_id(document_id)
    if not doc:
        raise NotFoundError("Document", document_id)

    # 1. Delete vectors
    _safe_delete_vectors(settings, document_id)

    # 2. Delete file directory
    upload_dir = Path(settings.upload_dir) / document_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)

    # 3. Delete database record
    repo.delete(document_id)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
