"""Document ingestion pipeline: validation, text extraction, sanitisation, chunking, and embedding."""
from __future__ import annotations

import logging
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import AISettings, get_settings
from app.integrations.embeddings_factory import create_embeddings
from app.integrations.vectorstore_factory import get_vectorstore
from app.models.document import Document, DocumentChunkMetadata

logger = logging.getLogger(__name__)

# Flagged prompt injection / instruction patterns
SUSPICIOUS_PATTERNS: tuple[str, ...] = (
    "ignore previous",
    "ignore all previous",
    "disregard",
    "forget your instructions",
    "you are now",
)

# Text splitter import with fallback
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ImportError:
        RecursiveCharacterTextSplitter = None  # type: ignore[assignment, misc]


class _FallbackSplitter:
    """Fallback recursive text splitter when langchain_text_splitters is unavailable."""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        start = 0
        text_len = len(text)
        step = max(1, self.chunk_size - self.chunk_overlap)
        while start < text_len:
            end = min(text_len, start + self.chunk_size)
            chunks.append(text[start:end])
            start += step
        return chunks


def validate_file(
    path: str | Path,
    mime: str | None = None,
    size_bytes: int | None = None,
    settings: AISettings | None = None,
) -> None:
    """Validate document extension, MIME sniffing, file size, page limits, and encryption.

    Raises ValueError with specific diagnostic reasons upon failure.
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"File does not exist: {path}")

    active_settings = settings or get_settings()

    # 1. Size check
    actual_size = p.stat().st_size
    effective_size = size_bytes if size_bytes is not None else actual_size
    if effective_size == 0:
        raise ValueError("Uploaded file is empty (0 bytes)")

    max_bytes = active_settings.max_upload_size_mb * 1024 * 1024
    if effective_size > max_bytes:
        raise ValueError(
            f"File size ({effective_size} bytes) exceeds maximum allowed {active_settings.max_upload_size_mb} MB"
        )

    # 2. Extension check
    ext = p.suffix.lower()
    allowed_extensions = {".pdf", ".docx", ".txt"}
    if ext not in allowed_extensions:
        raise ValueError(f"Unsupported file extension: '{ext}'. Allowed extensions: .pdf, .docx, .txt")

    # Read header sample for magic byte sniffing
    with open(p, "rb") as f:
        header_sample = f.read(2048)

    # 3. Format-specific validation & encryption checks
    if ext == ".pdf":
        if not header_sample.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF file: missing %PDF magic header")

        # Check PDF encryption and page count via pypdf if available
        try:
            import pypdf

            reader = pypdf.PdfReader(str(p))
            if reader.is_encrypted:
                raise ValueError("Encrypted or password-protected PDF files are not supported")
            if len(reader.pages) > 500:
                raise ValueError(
                    f"PDF document exceeds maximum limit of 500 pages (found {len(reader.pages)})"
                )
        except ImportError:
            # Fallback byte pattern inspection
            with open(p, "rb") as f:
                raw_bytes = f.read(65536)
            if b"/Encrypt" in raw_bytes:
                raise ValueError("Encrypted or password-protected PDF files are not supported")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to inspect PDF structure: {e}")

    elif ext == ".docx":
        # Check for encrypted OLE Compound File header
        if header_sample.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ValueError("Encrypted Office documents are not supported")
        if not header_sample.startswith(b"PK\x03\x04"):
            raise ValueError("Invalid DOCX file: not a valid zip archive")

        try:
            with zipfile.ZipFile(str(p), "r") as zf:
                namelist = zf.namelist()
                for name in namelist:
                    lower_name = name.lower()
                    if "vbaproject.bin" in lower_name or (
                        "vba" in lower_name and lower_name.endswith((".bin", ".xml"))
                    ):
                        raise ValueError("Macro-enabled documents are rejected for security")
                for info in zf.infolist():
                    if info.flag_bits & 0x1:
                        raise ValueError("Encrypted DOCX archives are not supported")
                if "word/document.xml" not in namelist:
                    raise ValueError("Invalid DOCX file: missing word/document.xml")
        except zipfile.BadZipFile:
            raise ValueError("Corrupted or invalid DOCX archive")

    elif ext == ".txt":
        if b"\x00" in header_sample:
            raise ValueError("Binary content or null bytes detected in text file")
        if header_sample.startswith(b"MZ"):
            raise ValueError("Executable files disguised as text are not allowed")

    # 4. MIME compatibility check
    if mime:
        mime_lower = mime.lower().strip()
        if ext == ".pdf":
            if not ("pdf" in mime_lower or mime_lower == "application/octet-stream"):
                raise ValueError(f"MIME type '{mime}' does not match .pdf extension")
        elif ext == ".docx":
            valid_docx_mimes = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/zip",
                "application/octet-stream",
            )
            if not any(valid in mime_lower for valid in valid_docx_mimes):
                raise ValueError(f"MIME type '{mime}' does not match .docx extension")
        elif ext == ".txt":
            if not (mime_lower.startswith("text/") or mime_lower == "application/octet-stream"):
                raise ValueError(f"MIME type '{mime}' does not match .txt extension")


def extract_text(path: str | Path, mime: str | None = None) -> list[dict[str, Any]]:
    """Extract structured text from PDF, DOCX, or TXT file preserving page and section hierarchy.

    Returns a list of dicts with keys: {'text': str, 'page': int | None, 'section': str | None}.
    Raises ValueError if no text can be extracted.
    """
    p = Path(path)
    ext = p.suffix.lower()
    pages: list[dict[str, Any]] = []

    if ext == ".pdf":
        # 1. Try pypdf
        try:
            import pypdf

            reader = pypdf.PdfReader(str(p))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF files are not supported")
            for idx, page in enumerate(reader.pages, start=1):
                txt = page.extract_text() or ""
                if txt.strip():
                    pages.append({"text": txt.strip(), "page": idx, "section": None})
            if pages:
                return pages
        except ImportError:
            pass
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("pypdf extraction failed, attempting pdfplumber: %s", exc)

        # 2. Try pdfplumber
        try:
            import pdfplumber

            with pdfplumber.open(str(p)) as pdf:
                for idx, page in enumerate(pdf.pages, start=1):
                    txt = page.extract_text() or ""
                    if txt.strip():
                        pages.append({"text": txt.strip(), "page": idx, "section": None})
            if pages:
                return pages
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("pdfplumber extraction failed: %s", exc)

        raise ValueError("No extractable text found in PDF document (scanned PDFs without OCR are not supported)")

    elif ext == ".docx":
        # 1. Try python-docx
        try:
            import docx

            doc = docx.Document(str(p))
            current_section: str | None = None
            for para in doc.paragraphs:
                txt = para.text.strip()
                if not txt:
                    continue
                if para.style and para.style.name and para.style.name.lower().startswith("heading"):
                    current_section = txt
                pages.append({"text": txt, "page": 1, "section": current_section})
            if pages:
                return pages
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("python-docx extraction failed, attempting XML fallback: %s", exc)

        # 2. Fallback to OpenXML standard library parsing
        try:
            with zipfile.ZipFile(str(p), "r") as zf:
                if "word/document.xml" in zf.namelist():
                    xml_content = zf.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    current_section = None
                    for para in tree.iter(f"{{{ns['w']}}}p"):
                        p_style = para.find(f".//{{{ns['w']}}}pStyle")
                        texts = [node.text for node in para.iter(f"{{{ns['w']}}}t") if node.text]
                        para_txt = "".join(texts).strip()
                        if not para_txt:
                            continue
                        if p_style is not None:
                            val = p_style.attrib.get(f"{{{ns['w']}}}val", "")
                            if "heading" in val.lower():
                                current_section = para_txt
                        pages.append({"text": para_txt, "page": 1, "section": current_section})
            if pages:
                return pages
        except Exception as exc:
            logger.warning("DOCX XML extraction failed: %s", exc)

        raise ValueError("No extractable text found in DOCX document")

    elif ext == ".txt":
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                with open(p, "r", encoding=enc) as f:
                    content = f.read()
                if content.strip():
                    return [{"text": content.strip(), "page": 1, "section": None}]
            except UnicodeDecodeError:
                continue

        raise ValueError("No extractable text found in TXT document")

    raise ValueError(f"Unsupported file extension '{ext}' for text extraction")


def sanitise_text(text: str) -> tuple[str, list[str]]:
    """Strip non-printable control characters and flag suspicious instruction-like patterns."""
    clean_chars = [
        ch for ch in text
        if ch in ("\n", "\r", "\t") or not unicodedata.category(ch).startswith("C")
    ]
    clean_text = "".join(clean_chars)

    lower_text = clean_text.lower()
    warnings: list[str] = []
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern in lower_text:
            warnings.append(f"Suspicious instruction pattern detected: '{pattern}'")

    return clean_text, warnings


def chunk_documents(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chunk documents using RecursiveCharacterTextSplitter (800 chunk size, 120 overlap).

    Preserves heading and page metadata for each chunk.
    """
    if RecursiveCharacterTextSplitter is not None:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=120,
            separators=["\n\n", "\n", " ", ""],
        )
    else:
        splitter = _FallbackSplitter(chunk_size=800, chunk_overlap=120)

    chunks: list[dict[str, Any]] = []
    chunk_index = 0

    for item in pages:
        txt = item.get("text", "")
        page_num = item.get("page")
        section = item.get("section")

        splits = splitter.split_text(txt)
        for piece in splits:
            cleaned = piece.strip()
            if not cleaned:
                continue
            chunks.append({
                "text": cleaned,
                "metadata": {
                    "page": page_num,
                    "section": section,
                    "chunk_index": chunk_index,
                },
            })
            chunk_index += 1

    return chunks


def embed_and_store(
    chunks: list[dict[str, Any]],
    document: Document,
    settings: AISettings,
    db: Session,
) -> int:
    """Batch embed and store chunks in the vector store and persist DocumentChunkMetadata records."""
    if not chunks:
        return 0

    vectorstore = get_vectorstore(settings)
    texts = [c["text"] for c in chunks]

    uploaded_at_iso = (
        document.uploaded_at.isoformat()
        if document.uploaded_at
        else datetime.now(timezone.utc).isoformat()
    )

    metadatas: list[dict[str, Any]] = []
    for c in chunks:
        meta: dict[str, Any] = {
            "document_id": document.id,
            "doc_name": document.name,
            "category": document.category,
            "version": document.version,
            "chunk_index": c["metadata"].get("chunk_index", 0),
            "active": document.active,
            "uploaded_at": uploaded_at_iso,
        }
        if c["metadata"].get("page") is not None:
            meta["page"] = c["metadata"]["page"]
        if c["metadata"].get("section") is not None:
            meta["section"] = c["metadata"]["section"]
        metadatas.append(meta)

    # Batch add to vector store with retries
    max_retries = 3
    vector_ids: list[str] | None = None
    last_err: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            vector_ids = vectorstore.add_texts(texts=texts, metadatas=metadatas)
            break
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Attempt %d/%d to embed and store chunks failed: %s",
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                time.sleep(0.5 * attempt)

    if vector_ids is None and last_err is not None:
        raise last_err

    if not vector_ids or len(vector_ids) != len(chunks):
        vector_ids = [str(uuid.uuid4()) for _ in chunks]

    # Create DocumentChunkMetadata database rows
    chunk_records: list[DocumentChunkMetadata] = []
    for idx, c in enumerate(chunks):
        v_id = vector_ids[idx] if idx < len(vector_ids) else None
        meta_info = c.get("metadata", {})
        token_count = max(1, len(c["text"]) // 4)
        chunk_obj = DocumentChunkMetadata(
            id=str(uuid.uuid4()),
            document_id=document.id,
            chunk_index=meta_info.get("chunk_index", idx),
            vector_id=v_id,
            page=meta_info.get("page"),
            section=meta_info.get("section"),
            token_count=token_count,
        )
        chunk_records.append(chunk_obj)

    db.add_all(chunk_records)
    db.flush()
    return len(chunk_records)


def run_ingestion_pipeline(
    document_id: str,
    file_path: str,
    settings: AISettings,
    db_session_factory: Callable[[], Session],
) -> None:
    """Execute full ingestion pipeline in the background and update document status."""
    session: Session = db_session_factory()
    try:
        doc = session.get(Document, document_id)
        if not doc:
            logger.error("Document id %s not found in DB during ingestion", document_id)
            return

        doc.status = "PROCESSING"
        doc.error = None
        session.commit()

        # Step 1: Validate file
        validate_file(
            path=file_path,
            mime=doc.mime,
            size_bytes=doc.size_bytes,
            settings=settings,
        )

        # Step 2: Extract text
        raw_pages = extract_text(path=file_path, mime=doc.mime)
        if not raw_pages:
            raise ValueError("No extractable text found in document")

        # Step 3: Sanitise text
        sanitised_pages: list[dict[str, Any]] = []
        all_warnings: list[str] = []
        for p in raw_pages:
            clean_txt, warnings = sanitise_text(p["text"])
            if warnings:
                all_warnings.extend(warnings)
            if clean_txt.strip():
                sanitised_pages.append({
                    "text": clean_txt,
                    "page": p.get("page"),
                    "section": p.get("section"),
                })

        if not sanitised_pages:
            raise ValueError("No extractable text remained after sanitisation")

        # Step 4: Chunk documents
        chunks = chunk_documents(sanitised_pages)
        if not chunks:
            raise ValueError("Document produced 0 chunks after splitting")

        # Step 5: Embed & Store
        stored_count = embed_and_store(chunks, doc, settings, session)

        # Mark document READY
        doc.status = "READY"
        if all_warnings:
            unique_warnings = list(dict.fromkeys(all_warnings))
            doc.error = f"Warnings: {'; '.join(unique_warnings)}"
        else:
            doc.error = None
        session.commit()
        logger.info("Successfully ingested document %s (%d chunks)", doc.id, stored_count)
    except Exception as exc:
        logger.exception("Ingestion failed for document %s: %s", document_id, exc)
        session.rollback()
        try:
            doc = session.get(Document, document_id)
            if doc:
                doc.status = "FAILED"
                doc.error = str(exc)
                session.commit()
        except Exception as update_err:
            logger.exception("Failed to update document status to FAILED: %s", update_err)
    finally:
        session.close()
