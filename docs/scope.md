# Scope

## In scope (v1)
- Banking API service with all modules in the spec.
- AI chat with 5 agent nodes, RAG over PDF/DOCX/TXT, external research, HITL.
- Streamlit UI for customers and admins.
- SQLite (dev), Alembic, Docker Compose, tests, docs.

## Out of scope (v1)
- Real payment rails, KYC providers, real OTP/SMS delivery.
- Mobile apps, multi-tenant, multi-currency.
- Regulatory certification (RBI, PCI-DSS). Compliance requires a separate formal assessment.
- Production-grade HA, HSM-backed key storage.
- Voice, image documents (scanned PDFs without OCR).

## Non-functional scope
| Area | v1 target |
|---|---|
| Availability | Local single node |
| DB | SQLite (WAL mode); PostgreSQL migration path documented |
| Scale | Tens of concurrent users |
| Security | Controls in `security.md` |
| Data retention | Configurable; audit logs retained indefinitely in dev |

## Deferred / future
PostgreSQL, Redis (rate limits, caching), Celery/RQ for document ingestion, OIDC IdP, mTLS, Kubernetes, hybrid search + reranker, OCR.
