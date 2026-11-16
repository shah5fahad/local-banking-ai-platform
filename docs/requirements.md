# Requirements

## 1. Functional requirements

**FR-1 User management:** register, login, logout/token revocation, profile get/update, change password, session management, account info. Strict per-user data isolation.

**FR-2 Bank accounts and beneficiaries:** add/list/get/update/deactivate accounts, verify account, manage beneficiaries. Account numbers always masked. Beneficiary create/modify requires verification and approval.

**FR-3 Transfers:** create, get, list/filter history (date, type, amount, status, beneficiary, reference), status, cancel pending, limits. Pipeline: beneficiary validation, balance, limits, duplicate prevention, authorization, confirmation, execution, status tracking, audit. States: `PENDING_APPROVAL, AUTHORIZED, PROCESSING, COMPLETED, FAILED, CANCELLED`. Idempotency keys mandatory.

**FR-4 Loans:** list offers, offer details, eligibility, apply, status, history, repayment details, active loans. Backend re-validates all rules.

**FR-5 Credit cards:** list, details, outstanding balance, statements, bills, bill payment, payment history, payment status. Duplicate payment prevention. No plaintext card data.

**FR-6 AI chat:** natural-language routing to (a) banking APIs, (b) policy RAG, (c) external research, (d) HITL, (e) out-of-domain rejection. Agents: Supervisor, Banking Ops, Policy RAG, External Research, Response.

**FR-7 HITL:** LangGraph interrupt/resume for beneficiary, transfer, loan, card payment. Confirmation and authentication are separate steps.

**FR-8 Frontend:** auth, chat, history (search/rename/delete), admin-only document management, admin dashboard (stats, users, roles, monitoring, audit, agent executions, config).

**FR-9 Documents:** PDF/DOCX/TXT upload, validation, extraction, chunking, embedding, versioning, activate/deactivate, delete with vectors.

## 2. Non-functional requirements
- **Security:** see `security.md`. AI is never a security boundary.
- **Consistency:** DB transactions for money movement; idempotent execution.
- **Auditability:** immutable audit log for sensitive operations.
- **Configurability:** LLM, embeddings, vector store selected via env vars.
- **Maintainability:** typed Python, layered modules, >80% coverage on services.
- **Observability:** structured JSON logs with correlation IDs, PII masked.
- **Portability:** Docker Compose; documented PostgreSQL migration path.
- **Performance (demo targets):** p95 read API < 300 ms; chat first token < 3 s excluding LLM latency.

## 3. Assumptions
1. Single-tenant, single-currency (INR), India-style fields (IFSC).
2. "Execution" of transfers is simulated internally (ledger debit/credit in the local DB); no real payment rails.
3. Transaction authentication = backend-verified transaction PIN (primary) with optional simulated OTP; collected by UI directly to the banking service, never through the LLM.
4. Beneficiary "verification" is simulated (penny-drop mock).
5. Roles: `CUSTOMER`, `ADMIN` (optional `AUDITOR`, read-only).
6. Service-to-service calls carry the end user's JWT plus a service credential.
7. One LLM provider active at a time; embedding model fixed per vector collection.
8. Streamlit is acceptable for demo; no mobile app.
9. Document corpus is small (<1,000 docs).
10. Loan/card data is seeded simulated data.

## 4. Security-sensitive workflows
Beneficiary add/modify, transfers, card bill payment, loan application, password change, role change, document upload (prompt-injection vector), admin chat monitoring (PII exposure), token handling between services.

## 5. Open questions
1. Transaction authentication: PIN only, OTP only, or both? How is OTP delivered in a local demo (console, mock SMS)?
Ans. PIN only
2. Which LLM and embedding providers should be default (OpenAI, Anthropic, Azure, Ollama local)?
Ans. Gemini
3. ChromaDB vs FAISS preference? (Recommendation: ChromaDB for metadata filtering and persistence.)
Ans. ChromaDB
4. Which external search provider (Tavily, SerpAPI, Bing, DuckDuckGo)? Allowed-domain list?
Ans. DuckDuckGo
5. Transfer rails to simulate: IMPS/NEFT/RTGS/UPI with different limits and fees?
Ans. IMPS/NEFT/RTGS
6. Fee/charge model and daily/per-transaction limits?
Ans. No limit
7. Can admins view full chat content or only masked? Retention period?
Ans. No admin allow to view the user chat content.
8. Is account-to-account transfer between a user's own accounts in scope?
Ans. Yes
9. Should the banking service support multi-account per user with a default account for chat transfers?
Ans. Yes multi account support
10. Is Argon2 (preferred) acceptable, and any minimum password policy?
Ans. Yes
11. Is the AI service allowed to keep a copy of user identifiers only (`ChatUserReference`)?
Ans. Yes
12. Multi-language chat (Hindi/English) needed?
Ans. Only English
13. Expected approval expiry (proposal: 5 min for transfers, 30 min for loans)?
Ans. Yes
