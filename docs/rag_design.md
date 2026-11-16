# RAG Design

## 1. Pipeline
1. **Upload** (`POST /documents`, admin). Store raw file in `data/uploads/<uuid>` (outside web root), record `Document(status=UPLOADED)`.
2. **Validate:** extension + MIME sniffing (magic bytes), max size (default 20 MB), max pages (500), reject encrypted/macro-enabled/embedded-executable content, SHA-256 dedupe, filename sanitised.
3. **Extract text:** PDF (`pypdf`/`pdfplumber`), DOCX (`python-docx`), TXT (UTF-8 with fallback detection). Preserve page numbers and heading hierarchy. Scanned PDFs with no text → `FAILED: no_text` (OCR deferred).
4. **Sanitise:** strip control chars; flag suspicious instruction-like patterns ("ignore previous instructions") into `document.warnings` for admin review; content is still treated as untrusted at query time.
5. **Chunk:** structure-aware recursive splitter, 800 tokens, 120 overlap (configurable), keep heading path in metadata.
6. **Embed:** `EmbeddingsFactory` (provider via env). Batch with retries.
7. **Store:** vector store collection `policy_docs__<embedding_model_id>`; metadata: `document_id, doc_name, category, version, page, section, chunk_index, active, uploaded_at`.
8. **Retrieve:** query rewrite (conversation-aware) → similarity search top-k (default 6) with metadata filter `active=true` (+ optional category) → min score threshold → optional MMR/rerank.
9. **Generate:** grounded prompt with numbered passages; model must cite `[n]`; response agent maps to `{doc name, version, page, section}`.
10. **Insufficient info:** if no chunk passes threshold or model reports unsupported → say so; do not guess.

Ingestion runs as a background task (FastAPI BackgroundTasks in v1; worker queue later). Status transitions: `UPLOADED → PROCESSING → READY | FAILED`.

## 2. Versioning
`doc_group_id` + `version`. Activating a new version deactivates the previous in one operation (metadata update in vector store + DB). Old versions kept for audit unless deleted.

## 3. Deletion
Delete chunks by `document_id` filter in vector store, then rows, then raw file; audit-logged. Reprocess = delete vectors + rerun pipeline.

## 4. Access control
- Only active docs retrievable. Category can be tagged `INTERNAL_STAFF`; customers' queries filter to `CUSTOMER_VISIBLE` categories (configurable).
- Documents contain **policy, not customer data**; upload UI warns admins. Detected account-number patterns trigger a warning/block.
- Admin-only management enforced in backend.

## 5. Embedding model change
Changing the embedding model requires a new collection and full re-embedding (migration job). Collection name encodes model id to prevent mixing.

## 6. Quality
Gold Q&A set per document, metrics: hit@k, MRR, groundedness (answer claims supported by cited chunks), refusal correctness. See `testing.md`.
