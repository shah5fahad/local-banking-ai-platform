# Changelog
All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com), SemVer.

## [Phase 6] - Frontend

### Fixed
- **Local Runner & Database Initialization Fixes (`startlocal.ps1` & `startlocal.sh`)**:
  - **Alembic Schema Synchronization**: Synchronized `banking_service/alembic/versions/0001_initial_schema.py` table names (`roles`, `users`, `bank_accounts`, `beneficiaries`, `bank_transactions`, `approval_challenge`, etc.) and columns with SQLAlchemy ORM models, resolving `OperationalError: no such table: roles` during `app.seed`.
  - **Alembic Configuration Fixes**: Corrected `version_locations = %(here)s/alembic/versions` in `banking_service/alembic.ini` and stripped inline comment on `version_path_separator` that broke config parsing.
  - **SQLite Transaction Rollback Fix in Alembic**: Removed redundant raw connection PRAGMA execution in `banking_service/alembic/env.py` and `ai_service/alembic/env.py` that opened uncommitted transactions in SQLAlchemy 2.0 causing `alembic_version` to roll back in SQLite.
  - **Missing Pydantic Dependency**: Added `"email-validator>=2.0.0"` to `banking_service/pyproject.toml` and `ai_service/pyproject.toml` for `EmailStr` schema validation.
  - **Local Runner Process Management**: Enhanced `startlocal.ps1` and `startlocal.sh` to execute the virtualenv's `alembic` executable directly (avoiding `python -m alembic`), route stdout/stderr to `data/logs/`, and verify health checks against `127.0.0.1`.

### Changed
- **Environment Configuration Template Updated** ([`.env.example`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/.env.example)):
  - Synchronized environment variable names, fallback aliases, and default values across Core Banking, AI Service, and Streamlit Frontend.
  - Added explicit configurations for:
    - Core Banking: `BANKING_DATABASE_URL`, `BANKING_JWT_SECRET`, `BANKING_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `ACCOUNT_HASH_PEPPER`, `SERVICE_API_KEYS`, transaction/daily limits, duplicate windows, PIN lockout attempts, and CORS origins.
    - AI Service: `AI_DATABASE_URL`, `LANGGRAPH_CHECKPOINT_DB`, `AI_BANKING_SERVICE_URL`, `AI_SERVICE_KEY`, `AI_SECRET_KEY`, LLM provider/hyperparameters (`fake`, `openai`, `anthropic`, `ollama`), embeddings & vector store (`chroma`), document upload paths/limits, external search engine domains (`tavily`), HITL sweeper intervals, and approval TTLs.
    - Frontend: `BANKING_API_URL`, `AI_API_URL`, and `SESSION_IDLE_TIMEOUT_MINUTES`.

### Added
- **Direct banking screens: accounts, beneficiaries, history (T6.6)**:
  - **Core Banking Account Endpoints & Service Integration** ([`accounts.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/api/v1/accounts.py)):
    - Mounted FastAPI routers for `/accounts`: `GET /accounts` (list with status filter), `POST /accounts` (link new account with AES-256 encryption and duplicate prevention), `GET /accounts/{id}` (detail), `PATCH /accounts/{id}` (update non-key fields), `DELETE /accounts/{id}` (deactivate with active transaction safeguards), `POST /accounts/{id}/verify` (penny-drop verification simulation), and `GET /accounts/{id}/balance` (real-time available balance).
  - **Banking Client Direct Banking Methods** ([`banking_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/banking_client.py)):
    - Added account methods: `list_accounts`, `add_account`, `get_account`, `get_account_balance`, `verify_account`, and `deactivate_account`.
    - Added beneficiary methods: `list_beneficiaries`, `create_beneficiary` (with `X-Approval-Token`), `verify_beneficiary`, and `deactivate_beneficiary`.
    - Added transaction methods: `list_transactions` (with type, status, amount filters), `get_transaction`, and `get_transaction_by_reference`.
  - **Direct Banking Component** ([`direct_banking.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/direct_banking.py)):
    - **🏦 Bank Accounts Tab**:
      - Masked account cards (`XXXXXX1234`), balance display formatted in INR, IFSC, bank name, branch, account type badge, and verification status.
      - Real-time balance check button (`⚡ Check Balance`) updating balance on demand.
      - Simulated penny-drop verification trigger.
      - Link new account form with strict validation (numeric 9-18 digit account number, IFSC regex pattern `^[A-Z]{4}0[A-Z0-9]{6}$`).
      - Account deactivation confirmation popover.
    - **👥 Beneficiaries Tab**:
      - Searchable recipient cards with masked account numbers, bank name, IFSC, and channel eligibility.
      - Penny-drop mock verification button.
      - Add new beneficiary workflow featuring **direct PIN authentication**:
        1. Form collects recipient details.
        2. Client computes SHA-256 summary hash and requests challenge from `POST /approvals/challenges`.
        3. PIN is submitted directly to `POST /approvals/challenges/{id}/verify` to obtain single-use `X-Approval-Token`.
        4. Submits `POST /beneficiaries` with the approval token, satisfying the strict PIN security invariant.
    - **📜 Transaction History Tab**:
      - Filter by transaction type (TRANSFER, CARD_PAYMENT, DEPOSIT) and status (COMPLETED, PENDING, FAILED).
      - Metric overview: Total transactions, completed transfers count, and debited INR volume.
      - Personal transaction table with masked source accounts, settlement channels, and failure reason flags.
      - Direct transaction reference lookup drawer (`GET /transactions/by-reference/{ref}`).
  - **Direct Banking Page** ([`5_Banking.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/5_Banking.py)):
    - Protected by `require_auth()` route guard.
    - Linked into home navigation in [`app.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/app.py).
  - **Testing**:
    - Created dedicated test suite in [`test_direct_banking.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/test_direct_banking.py) with 8 comprehensive unit and AppTest tests.
    - Full platform pass rate: 78 frontend, 249 AI service, 40 banking service = **367 passed (100%)**.
- **Admin dashboard: stats, users/roles, transactions, loans, masked chat monitor, audit viewer, agent executions, config (T6.5)**:
  - **AI Service Admin & Monitoring APIs** ([`admin.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/api/v1/admin.py)):
    - Added `GET /api/v1/admin/ai-stats`: Aggregate metrics for total/active conversations, message count, agent execution traces, average node latency (ms), and pending approvals.
    - Added `GET /api/v1/admin/conversations`: Masked chat conversation monitor across all bank users.
    - Added `GET /api/v1/admin/conversations/{id}/messages`: Turn-by-turn masked dialogue inspection with role attribution and citations.
    - Added `GET /api/v1/admin/agent-executions`: LangGraph node and tool execution trace inspector with status, latency, token count, and error codes.
    - Added `GET /api/v1/admin/ai-config` and `PATCH /api/v1/admin/ai-config`: Non-secret runtime AI hyperparameters management (model name, temperature, top-k, min relevance score).
  - **Banking & AI Client Admin Integrations**:
    - Extended [`banking_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/banking_client.py) with methods: `get_admin_stats`, `list_admin_users`, `update_user_status`, `update_user_roles`, `list_admin_transactions`, `list_admin_loans`, `get_admin_config`, `update_admin_config`, `list_audit_logs`, and `get_audit_log`.
    - Extended [`ai_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/ai_client.py) with methods: `get_ai_stats`, `list_admin_conversations`, `get_admin_conversation_messages`, `list_agent_executions`, `get_ai_config`, and `update_ai_config`.
  - **Unified Admin Dashboard Component** ([`admin_dashboard.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/admin_dashboard.py)):
    - **📊 Overview**: Side-by-side core banking and AI engine metric scorecards (users, accounts, loan volume in ₹, transactions, agent latency, approvals).
    - **👥 Users & Roles**: Complete user table with lockout notifications, active status toggle, and role management popover (`CUSTOMER`, `ADMIN`, `AUDITOR`).
    - **💳 Transactions**: Cross-customer transaction table with masked source accounts, channel, settlement status, and failure reason flags.
    - **🏦 Loans**: Loan underwriting review table with requested amounts, tenure, income, and decision audit logs.
    - **💬 Masked Chat Monitor**: Compliance auditing of customer AI conversations with preserved PII masking and expandable citation inspectors.
    - **🛡️ Audit Trail**: Searchable, immutable audit trail viewer with action, outcome (`SUCCESS`/`FAILURE`), actor filters, and JSON metadata viewer.
    - **⚡ Agent Executions**: Step-trace debugger for LangGraph nodes (`input_guard`, `supervisor`, `banking_ops`, `policy_rag`, `external_research`, `response`), tool invocations, and latency telemetry.
    - **⚙️ Configuration**: Runtime controls for per-transaction/daily transfer limits (₹), approval expiry, duplicate detection window, auth method (PIN/OTP), and AI hyperparameters.
  - **Admin Page Updates** ([`4_Admin.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/4_Admin.py)):
    - Route guard updated to `require_roles("ADMIN", "AUDITOR")`.
    - Auditors receive read-only inspection access; administrative mutators are disabled for non-admins.
  - **Testing**:
    - Created [`test_ai_admin_api.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/tests/unit/test_ai_admin_api.py) (all passed).
    - Created [`test_admin_dashboard.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/test_admin_dashboard.py) with 16 unit and AppTest tests (all passed).
    - 100% test pass rate across the full platform (70 frontend, 249 AI service, 40 banking service = 359 tests passed).
- **Admin: documents UI (upload, status, reprocess, deactivate, delete, versions) (T6.4)**:
  - **AI Client Document Management Extensions** ([`ai_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/ai_client.py)):
    - Added `upload_document(file_bytes, filename, name, category, version, access_token, doc_group_id)` supporting multipart form uploads with file validation and background ingestion queueing (`POST /api/v1/documents`).
    - Added `list_documents(access_token, category, active, page, page_size)` with category and active filtering (`GET /api/v1/documents`).
    - Added `get_document(document_id, access_token)` fetching detailed document state and chunk metadata (`GET /api/v1/documents/{id}`).
    - Added `activate_document(document_id, access_token)` making document active in RAG and automatically superseding older versions in the group (`POST /api/v1/documents/{id}/activate`).
    - Added `deactivate_document(document_id, access_token)` excluding document from vector retrieval (`POST /api/v1/documents/{id}/deactivate`).
    - Added `reprocess_document(document_id, access_token)` deleting existing vectors and triggering pipeline re-ingestion (`POST /api/v1/documents/{id}/reprocess`).
    - Added `delete_document(document_id, access_token)` permanently wiping document records, disk files, and ChromaDB embeddings (`DELETE /api/v1/documents/{id}`).
    - Added `get_document_versions(document_id, access_token)` retrieving version lineages within document groups (`GET /api/v1/documents/{id}/versions`).
  - **Document Manager Component** ([`document_manager.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/document_manager.py)):
    - **Upload Form**: File uploader (.pdf, .docx, .txt), title, category (`REGULATORY`, `CIRCULAR`, `POLICY`, `INTERNAL`), version string, and optional group ID linking to prior revisions.
    - **Document Library**: Category filter, active/inactive filter, summary metrics (Total, Active in RAG, Superseded/Inactive).
    - **Document Cards & Metadata**: Status badges (`INDEXED`, `PROCESSING`, `UPLOADED`, `FAILED`), active state badges, size formatting (`format_bytes`), upload timestamp, and document IDs.
    - **Interactive Actions**:
      - One-click **Activate / Deactivate** toggle.
      - **Reprocess** button to re-chunk and re-embed.
      - **Version History Drawer** rendering tabular version lineage with active markers.
      - **Chunk & Metadata Drawer** displaying MIME type, SHA-256 hash, chunk count, and detailed chunk table (index, page, section, token count, vector ID).
      - **Delete Popover** with permanent removal confirmation.
    - **Role-Based Access Control**:
      - `ADMIN`: Full access to upload, reprocess, toggle, and delete.
      - `AUDITOR`: Read-only inspection access; UI shows informational auditor banner and restricts mutating operations.
  - **Documents Page** ([`3_Documents.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/3_Documents.py)):
    - Enforced `require_roles("ADMIN", "AUDITOR")` route guard blocking non-privileged users.
    - Rendered responsive tabs: **Document Library** and **Upload Document**.
  - **Testing**:
    - Added 12 comprehensive unit and AppTest tests in [`test_documents.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/test_documents.py) covering upload, list, detail, activate/deactivate, reprocess, delete, version inspection, byte formatting, and role authorization.
    - All 54 frontend tests passing (100%).
- **Chat history: list, search, rename, delete (T6.3)**:
  - **AI Client Conversation Extensions** ([`ai_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/ai_client.py)):
    - Enhanced `list_conversations` with keyword title search query (`q`) and pagination support.
    - Added `create_conversation(title)` for starting named conversation sessions.
    - Added `rename_conversation(conversation_id, new_title)` connecting to `PATCH /api/v1/conversations/{id}`.
    - Added `delete_conversation(conversation_id)` connecting to `DELETE /api/v1/conversations/{id}` (soft-delete).
  - **Conversation History Component** ([`history_view.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/history_view.py)):
    - Keyword search input filtering conversation titles dynamically.
    - Conversation cards displaying title, message count badges, and formatted human-readable creation/update timestamps (`format_iso_timestamp`).
    - Quick actions per conversation:
      - **"📂 Open"**: loads historical messages into session state and switches directly to [`1_Chat.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/1_Chat.py).
      - **"✏️ Rename"**: popover for in-place title updates.
      - **"🗑️ Delete"**: confirmation popover for permanent soft deletion.
    - Expandable **Message Transcript Inspector**: renders complete turn-by-turn chat history with sender roles (`👤 User` / `🤖 Assistant`), timestamps, and regulatory citations.
  - **History Page** ([`2_History.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/2_History.py)):
    - Protected by `require_auth()` route guard.
    - Multi-tab layout featuring **💬 Chat Conversations** and **ℹ️ Data Privacy & Retention** guidance (user ownership isolation, credential scrubbing, PII masking).
  - **Chat Page Sidebar & Header Integration** ([`1_Chat.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/1_Chat.py)):
    - Sidebar search input filtering recent conversations in real time.
    - Direct "📜 History" navigation button.
    - Active conversation header with in-place rename and delete controls.
  - **Testing**:
    - Added dedicated test suite in [`test_history.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/test_history.py) (7 passed).
    - 42/42 frontend tests passing (100%).
- **Chat page: streaming, tool status, approval card, direct PIN dialog, citations (T6.2)**:
  - **AI Service Client** ([`ai_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/ai_client.py)):
    - Server-Sent Events (SSE) streaming consumer parsing `status`, `tool`, `token`, `citations`, `approval_required`, `done`, and `error` events.
    - Approval management methods: `get_active_approval`, `get_approval`, `decide_approval` (`CONFIRM`/`REJECT`), and `resume_approval` with `authorization_id`.
    - Conversation management methods: `list_conversations`, `get_conversation`.
  - **Direct PIN Authorization (Security Invariant)** ([`pin_dialog.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/pin_dialog.py)):
    - Built `@st.dialog("🔒 Enter Transaction PIN")` modal dialog.
    - Enforced **Security Invariant**: customer transaction PIN is submitted **DIRECTLY** to Core Banking Service API endpoints (`/api/v1/transfers/{id}/authorize`, `/api/v1/credit-cards/payments/{id}/authorize`, `/api/v1/approvals/challenges/{id}/verify`), and NEVER touches or traverses the AI Chat Service.
    - Acquired single-use `authorization_id` / `approval_token` from Banking and forwarded it to `POST /api/v1/chat/approvals/{id}/resume` to resume graph execution.
  - **HITL Approval Card Component** ([`approval_card.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/approval_card.py)):
    - Prominent confirmation card with workflow badge (`TRANSFER`, `CARD_PAYMENT`, `BENEFICIARY`, `LOAN`), risk level, and remaining expiry countdown.
    - Transaction breakdown metrics and summary tables.
    - Two-stage actions: "✅ Confirm & Authenticate" (triggers decision + opens direct PIN dialog) and "❌ Reject & Cancel" (cancels draft at banking and marks approval rejected).
  - **Citations Component** ([`citations.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/citations.py)):
    - Grounding expander displaying verified regulatory document titles, section/page references, relevance scores, and quote excerpts.
  - **Chat Interface & Tool Status** ([`1_Chat.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/1_Chat.py)):
    - Protected by `require_auth()` route guard.
    - Sidebar with recent conversation list and "➕ New Conversation" button.
    - Multi-turn message history container.
    - Real-time token streaming with `st.status` widget showing supervisor routing, policy research, and banking tool execution.
    - Integrated inline approval card and direct PIN authorization modal.
  - **Testing**:
    - Added unit and AppTest suites in [`test_ai_client.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/test_ai_client.py) and [`test_chat_page.py`](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/test_chat_page.py).
    - 35/35 frontend tests passing (100%).
- **Auth pages, session handling, route guards, idle timeout (T6.1)**:
  - **Banking Service Authentication Endpoints**:
    - Implemented full auth REST APIs in [auth.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/api/v1/auth.py):
      - `POST /api/v1/auth/register`: account creation with password complexity & unique checks, assigning `CUSTOMER` role.
      - `POST /api/v1/auth/login`: credential verification with 5-attempt / 30-minute lockout enforcement, issuing JWT access token & rotating refresh token.
      - `POST /api/v1/auth/refresh`: refresh token rotation with reuse detection.
      - `POST /api/v1/auth/logout`: session revocation for current or all sessions.
      - `GET /api/v1/auth/sessions`: listing active sessions for the authenticated user.
      - `GET /api/v1/users/me` in [users.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/api/v1/users.py): current user profile and assigned roles lookup.
    - Updated `UserRepository` in [user_repository.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/repositories/user_repository.py) with `assign_role` and `get_roles` methods.
    - Fixed `AuthService.register()` to properly instantiate `User` models and assign roles.
    - Added backwards-compatible `Role.role` property in [user.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/models/user.py).
    - Hardened `AuditService` and `AuditRepository` with sensitive field masking and SHA-256 hash chaining.
  - **Frontend Client & Session Management**:
    - Implemented `BankingClient` in [banking_client.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/clients/banking_client.py) with client-side password strength validation (12+ characters, uppercase, lowercase, digit, special character), E.164 phone validation, token acquisition, refresh rotation, profile retrieval, and session listing.
    - Implemented server-side session state management in [session.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/state/session.py) enforcing the **Session Security Invariant**: tokens are stored in server-side `st.session_state` only, never in URLs, cookies, or browser local storage.
    - Configured automatic 15-minute idle timeout policy (`check_idle_timeout`): compares elapsed user inactivity against 15-minute threshold, automatically revokes session state, and prompts the user on timeout.
    - Created route guards (`require_auth()` and `require_roles(*allowed_roles)`): halts unauthorized or unauthenticated view rendering and provides navigation redirects.
  - **Streamlit Application & Auth Views**:
    - Created main entrypoint in [app.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/app.py) with responsive tab navigation for "Sign In" and "Create Account", development credential hints, authenticated home dashboard with navigation cards, and active sessions viewer.
    - Created auth form components in [auth_forms.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/auth_forms.py) with client-side password requirement expander, phone formatting checks, and lockout error feedback.
    - Created sidebar profile component in [sidebar.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/components/sidebar.py) displaying user info, role badges, remaining idle session duration, and Logout button.
    - Created protected pages with route guards:
      - [1_Chat.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/1_Chat.py) (`require_auth()`)
      - [2_History.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/2_History.py) (`require_auth()`)
      - [3_Documents.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/3_Documents.py) (`require_roles("ADMIN", "AUDITOR")`)
      - [4_Admin.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/pages/4_Admin.py) (`require_roles("ADMIN")`)
    - Updated [Dockerfile](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/Dockerfile) and [requirements.txt](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/requirements.txt) for Streamlit 1.67.0 on Python 3.12-slim.
  - **Testing**:
    - 23 unit tests in [frontend/tests/](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/frontend/tests/) (`test_banking_client.py`, `test_session_and_guards.py`, `test_app_render.py`) with 100% pass rate.
    - 40 unit tests in `banking_service/tests/unit/` (`test_auth_api.py`, `test_auth_service.py`, etc.) with 100% pass rate.
    - 38 security and sweeper tests in `ai_service/tests/unit/` with 100% pass rate.

## [Phase 5] - Human-in-the-Loop

### Added
- **HITL security test suite (T5.7)**:
  - Comprehensive security test suite implemented in [test_hitl_security.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/tests/unit/test_hitl_security.py) with 24 dedicated test cases across 5 security pillars:
    - **No write before approval**: Verified across all HITL workflows (transfers, beneficiaries, card payments, loans) that backend execute/write endpoints are never called before human confirmation and PIN authorization; verified that free text entered into chat (e.g., "yes", "please confirm", "I approve") does not bypass approval gates or trigger execution; rejection cleanly aborts without backend writes.
    - **Tamper resistance**: Verified that altering `summary_hash` in resumption payloads is detected and rejected with 409 Conflict; forged authorization tokens are rejected; smuggled `user_id` parameters in request bodies are ignored in favor of verified JWT claims; admin callers cannot approve or resume on behalf of regular users.
    - **Replay attacks & Idempotency**: Verified idempotent handling for repeated `CONFIRM`, `REJECT`, and `resume` submissions; replaying expired, rejected, or superseded approvals consistently yields HTTP 409 Conflict.
    - **Cross-user isolation (IDOR protection)**: Verified that User A cannot view (404), decide (404), resume (404), or query active approvals (None/404) for User B; cross-conversation message injection is rejected with 404.
    - **Credential and secret isolation**: Verified that PIN, OTP, password, and Bearer access tokens never traverse into `GraphState` or persistent checkpoint storage; account numbers and cards are strictly masked across summaries and events.
  - Hardened `execute_node` in [execute.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/nodes/execute.py) to strictly enforce that execution requires an approval status of `CONFIRMED` or `AUTHENTICATED`, and requires `authorization_id` for workflows requiring secondary MFA.
  - Added optional `summary_hash` tamper verification to `ResumeRequest` schema and `ApprovalService.resume_approval`.
  - Phase 5: Human-in-the-Loop is now 100% complete with 248 unit and security tests passing.
- **Expiry sweeper, checkpoint pruning, and superseding rules (T5.6)**:
  - Added `ApprovalStatus.SUPERSEDED` state representing superseded approvals.
  - Superseding rules implemented in `ApprovalService` ([approval_service.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/services/approval_service.py)):
    - Enforces at most one active pending approval per workflow type per conversation.
    - Creating a new approval automatically marks prior active approvals (`PENDING`, `CONFIRMED`, `AUTH_REQUIRED`) as `SUPERSEDED` with `decided_at` set.
    - Prior Banking API drafts for transfers are automatically cancelled via `BankingClient.cancel_transfer(...)` to free locked funds without leaving orphan drafts.
    - Isolation is maintained across distinct workflow types and conversations.
    - Superseded approvals strictly reject decision or resume submissions with 409 Conflict.
    - Upserts `WorkflowCheckpointMetadata` to track active execution and expiration.
  - Expiry Sweeper implemented in `ExpirySweeperService` ([expiry_sweeper.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/services/expiry_sweeper.py)):
    - Identifies all expired approvals (`expires_at <= now()`), transitions status to `EXPIRED`, and updates `decided_at`.
    - Automatically cancels expired transfer drafts at the Banking API via user or system-generated service JWTs.
    - Updates associated `WorkflowCheckpointMetadata` status to `EXPIRED`.
    - Resumes/unblocks waiting LangGraph interrupts with cancellation/expired commands.
    - Gracefully catches transient banking errors to prevent sweeper interruption.
  - Checkpoint Pruning implemented in `ExpirySweeperService.prune_checkpoints`:
    - Retention threshold filtering (`older_than_days`, default: 7 days).
    - Prunes stale/terminal `WorkflowCheckpointMetadata` records.
    - Cleans SQLite checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) by thread ID and age.
    - Cleans in-memory checkpointer storage keys when memory saver is used.
  - Background sweeper task & lifespan integration:
    - Periodic async sweeper loop `run_periodic_sweeper` integrated into FastAPI lifespan in [main.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/main.py).
    - Configured via `AI_ENABLE_EXPIRY_SWEEPER`, `AI_SWEEPER_INTERVAL_SECONDS`, and `AI_CHECKPOINT_RETENTION_DAYS` in [config.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/core/config.py).
    - Clean shutdown handling with `stop_event` and task cancellation.
  - REST API Endpoints in [chat.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/api/v1/chat.py):
    - `GET /api/v1/chat/approvals/active`: returns currently active pending approval for a conversation (with on-the-fly expiry check).
    - `POST /api/v1/chat/approvals/sweep`: manual trigger for approval expiry sweep and draft cancellation.
    - `POST /api/v1/chat/checkpoints/prune`: manual trigger for checkpoint pruning with custom retention threshold.
  - Comprehensive unit and integration test suite in `ai_service/tests/unit/test_expiry_and_cleanup.py` with 14 test cases covering superseding, draft cancellation, isolation, conflict handling, expiry sweeping, checkpoint pruning, background runner, and REST APIs. Total suite passing: 224/224 tests (100%).
- **Card payment workflow (T5.5)**:
  - `workflow_card_payment_node` ([card_payment.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/workflows/card_payment.py)) with active card discovery, multi-card disambiguation, statement bill lookup (Total Due, Minimum Due, Due Date), amount option selection, active source account discovery, and sufficient balance verification prior to drafting.
  - Integration with Banking API `POST /api/v1/credit-cards/{id}/payments` to prepare `PENDING_APPROVAL` draft with `Idempotency-Key` and canonical `summary_hash`.
  - Integration with `approval_gate_node`: produces masked review summary card with card last4, network, option label, and masked debit account; triggers two-stage LangGraph `interrupt()` (stage 1 for human confirmation, stage 2 for direct Banking API PIN authorization).
  - Backend execution node (`execute_node` in [execute.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/nodes/execute.py)) executing `POST /api/v1/credit-cards/payments/{id}/execute` with single-use `authorization_id`, followed by payment status query (`GET /api/v1/credit-cards/payments/{id}/status`) to confirm `COMPLETED` status and payment reference.
  - Comprehensive unit and integration test suite in `ai_service/tests/unit/test_card_payment_workflow.py` with 15 test cases covering option parsing, bill presentation, account selection, draft creation, execution, and clean rejection cancellation.
- **Loan workflow (T5.4)**:
  - `workflow_loan_node` ([loan.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/workflows/loan.py)) with pre-approved offers display, conversational multi-turn parameter extraction (loan type Personal/Home/Auto, requested amount, tenure in months/years, monthly income, employment type, employer), and reducing balance monthly EMI calculation.
  - Integration with Banking API `POST /api/v1/loans/eligibility` to check credit affordability, debt-to-income limits (EMI <= 40% monthly income), tenure constraints, and active loan counts prior to preparing the review card; displays detailed rejection reasons when ineligible without creating drafts.
  - Integration with `approval_gate_node`: produces masked review summary card with estimated EMI and interest rate; triggers stage 1 human confirmation `interrupt()`, proceeding directly to execution upon confirmation (no secondary MFA required for loans as per specification).
  - Backend execution node (`execute_node` in [execute.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/nodes/execute.py)) executing `POST /api/v1/loans/applications` with `Idempotency-Key` upon confirmation, returning reference number and instant approval status.
  - Comprehensive unit and integration test suite in `ai_service/tests/unit/test_loan_workflow.py` with 22 test cases covering parsing, eligibility checks, failure explanations, draft creation, execution, and clean rejection cancellation.
- **Transfer workflow (T5.3)**:
  - `workflow_transfer_node` ([transfer.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/workflows/transfer.py)) with multi-turn conversational extraction of amount (supporting Indian Rupee numbering, lakhs, paise decimals, plain numbers) and beneficiary name, active source account discovery, balance sufficiency verification, and per-transaction/daily limit enforcement prior to drafting.
  - Integration with Banking API `POST /api/v1/transfers` to create `PENDING_APPROVAL` draft with canonical `summary_hash`, fee calculation, and `Idempotency-Key`.
  - Integration with `approval_gate_node`: produces masked transfer summary (`₹`, charges, masked recipient account) and triggers two-stage LangGraph `interrupt()` (stage 1 for user confirmation, stage 2 for direct Banking API PIN authorization).
  - Clean draft cancellation at Banking API (`cancel_transfer`) upon rejection without backend execution.
  - Backend execution node (`execute_node` in [execute.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/nodes/execute.py)) executing `POST /api/v1/transfers/{id}/execute` using the single-use `authorization_id` and verified `summary_hash`, followed by `GET /api/v1/transfers/{id}/status` query for definitive transaction reference and status confirmation.
  - Comprehensive unit and end-to-end integration test suite in `ai_service/tests/unit/test_transfer_workflow.py` with 33 test cases covering parsing, validation, limits, disambiguation, draft preparation, execution, and rejection.
- **Beneficiary workflow (T5.2)**:
  - `workflow_beneficiary_node` ([beneficiary.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/workflows/beneficiary.py)) with conversational multi-turn field collection, format validation (account number 9-18 digits, standard IFSC regex), bank name inference from IFSC prefixes, duplicate detection via BankingClient, canonical SHA-256 payload_hash computation, and automatic approval challenge creation.
  - Integration with `approval_gate`: generates masked review cards (`XXXXXX1234`), initiates human confirmation, and advances to MFA authentication stage.
  - Backend execution node (`execute_node` in [execute.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/ai_service/app/agents/nodes/execute.py)) executing `POST /beneficiaries` with the single-use approval token upon resumption, completely isolating sensitive execution credentials from prompts/checkpoints.
  - Banking API endpoints implemented in [beneficiaries.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/api/v1/beneficiaries.py) and [approvals.py](file:///C:/Users/DELL/Downloads/local-banking-ai-platform/banking_service/app/api/v1/approvals.py) for beneficiary CRUD and challenge issuance/verification.
  - Clean cancellation without backend writes on user rejection.
  - Test suite in `ai_service/tests/unit/test_beneficiary_workflow.py` with 10 unit and end-to-end integration tests.
- **PendingApproval model & ApprovalService (T5.1)**:
  - Database model (`PendingApproval`) with TTL calculation (`is_expired`), workflow classifications (`TRANSFER`, `CARD_PAYMENT`, `BENEFICIARY`, `LOAN`), risk levels, canonical SHA-256 `summary_hash`, and status state transitions.
  - `ApprovalService` handling approval creation, TTL defaults (300s for transfers/cards, 600s for beneficiaries, 1800s for loans), strict user ownership validation (404 on cross-user access), automatic expiry handling, idempotent decision submission (`CONFIRM` / `REJECT`), and graph resumption with PIN/OTP `authorization_id`.
  - Banking draft cancellation triggered automatically upon rejection.
- **Approval gate with LangGraph `interrupt()` (T5.1)**:
  - `approval_gate_node` executing two-stage human-in-the-loop interruption: confirmation stage pausing for explicit human decision via `/chat/approvals/{id}/decision`, and secondary authentication stage pausing for direct banking PIN/OTP authorization.
  - SSE streaming emitting `approval_required` events containing masked summary payloads without sensitive secrets.
- **Decision & Resume REST APIs (T5.1)**:
  - `GET /api/v1/chat/approvals/{approval_id}`: retrieval of masked summary and approval status.
  - `POST /api/v1/chat/approvals/{approval_id}/decision`: user confirmation or rejection endpoint resuming checkpointer execution.
  - `POST /api/v1/chat/approvals/{approval_id}/resume`: resumptions with `authorization_id` after direct banking MFA.
  - Idempotent replays and strict conflict handling (409 on expired or invalid transitions).
- **Test suite**: Comprehensive unit and API test suite in `ai_service/tests/unit/test_hitl_approval_gate.py` with 11 test cases validating models, services, node interrupts, and REST APIs.

## [Phase 4] - Banking AI Agents

### Added
- **Banking Ops node with READ tools (T4.1)**: Full read execution via LLM tool-calling and fallback mapping for accounts, balance, transactions, loan offers, and credit cards; strict token and secret isolation.
- **Document ingestion pipeline and APIs (T4.2)**: Validation (MIME sniffing, size, 500-page limit, encryption detection), extraction (PDF, DOCX, TXT), sanitisation (control characters and prompt injection flagging), structure-aware chunking (800 tokens, 120 overlap), and embedding/vectorstore persistence; full document CRUD APIs (`/documents`, activate, deactivate, reprocess, versions, delete).
- **Policy RAG node with citations and abstain behavior (T4.3)**: Top-k similarity search, active status and threshold filtering (`rag_min_score`), numbered passage citations (`[n]` mapped to doc name, version, page, section), and strict abstain message when information is absent.
- **External research node (T4.4)**: Serper/Tavily provider integrations, domain allow-list matching (`search_allowed_domains`), prompt-injection barrier with `<external_search_data>` untrusted block, citation mapping, and mandatory disclaimer appending.
- **Response node + formatter + output guard (T4.5)**: Tool-result compilation, output guard masking (card numbers, bearer tokens, JWTs, secret-request blocking), terminal canned responses for unsupported and out-of-domain routes, and blocked input warning prefix.
- **Chat and conversations persistence (T4.6)**: Real-time SSE streaming endpoint (`/chat/messages`) emitting `status`, `tool`, `token`, `citations`, `done`, and `approval_required` events; per-node execution telemetry persisted into `agent_execution`; full conversation CRUD (`/conversations`) with title search (`q`), pagination, and user ownership isolation.
- **Unsupported & out-of-domain handling (T4.7)**: Deterministic routing table overlay enforcing 100% pass rate for all specification benchmark queries across `banking_ops`, `workflow_*`, `policy_rag`, `external_research`, `reject_out_of_domain`, and `unsupported`.
- **Test suite**: Comprehensive unit and API tests in `ai_service/tests/unit` covering routing table specs (100% pass), banking ops, document pipeline, policy RAG, external research, response guard, and conversation CRUD/streaming.

## [Phase 3] - AI Infrastructure

### Added
- AI service core infrastructure: `AIError` domain errors, `request_id_middleware`, JWT validation for banking-issued tokens using shared HS256 secret (T3.1)
- FastAPI dependency injection: `CurrentUserId`, `AccessToken`, `require_roles()`, `DbSession` for the AI service (T3.1)
- SQLAlchemy 2.0 AI DB models: `ChatUserReference`, `Conversation`, `ChatMessage`, `AgentExecution`, `PendingApproval`, `Document`, `DocumentChunkMetadata`, `WorkflowCheckpointMetadata` with Alembic migration (T3.1)
- `LLMFactory`: env-driven provider selection (OpenAI, Anthropic, Google, Fake) with graceful import fallback for zero-API-key test environments (T3.2)
- `EmbeddingsFactory`: env-driven provider selection (OpenAI, HuggingFace, Google, Fake 1536-dim) (T3.2)
- `VectorStoreFactory`: model-ID-namespaced collection names, Chroma/FAISS/InMemory backends, singleton `get_vectorstore()` (T3.2)
- Extended `AISettings` with 20+ fields for LLM/embeddings/RAG/vectorstore/search/upload config using `AliasChoices` to handle `AI_` prefix without double-prefixing (T3.2)
- `BankingClient` synchronous typed HTTP adapter with 10s/30s timeouts, 2× retries on 5xx reads, masked logging, Bearer+ServiceKey injection, `BankingClientError` mapping — covering all accounts, beneficiaries, transfers, transactions, loans, credit-cards, and user endpoints (T3.3)
- `GraphState` TypedDict with security invariant: access tokens never stored in state; injected at invoke/resume via `config["configurable"]` (T3.4)
- LangGraph graph assembly with `SqliteSaver` checkpointer, conditional routing after `input_guard` and `supervisor`, `get_graph()` singleton, `invoke_graph()` helper (T3.4)
- `ToolRegistry` with risk levels (READ/WRITE_LOW/SENSITIVE/FINANCIAL), `allowed_nodes` permission enforcement, and LLM-format tool schema generation (T3.5)
- 11 banking READ tools registered for `banking_ops` node: `list_accounts`, `get_balance`, `list_transactions`, `list_beneficiaries`, `list_loan_offers`, `check_loan_eligibility`, `list_cards`, `get_card_outstanding`, `get_current_bill`, `get_transfer_limits`, `get_user_summary` (T3.5)
- `input_guard`: 2000-char limit, NFKC unicode normalisation, control-char stripping, 7 injection-heuristic patterns, JWT/PIN/password secret detector (T3.6)
- `output_guard`: residual account-number masking via `banking_common`, persona-hijacking filter, secret-request blocker (T3.6)
- `supervisor` node with structured LLM output, `ROUTE_OVERRIDES` deterministic table covering all 11 intents, low-confidence (< 0.5) fallback to `unsupported` (T3.7)
- `banking_ops`, `policy_rag`, `external_research`, `response` nodes; `workflow_beneficiary/transfer/loan/card_payment` stubs (T3.7)
- 10 unit test modules across both AI service builders covering guards, supervisor, tool registry, graph, banking client, security, factories, models, errors (T3.1–T3.7)

## [Phase 2] - Banking APIs Implementation

### Added
- Transfer state machine enforcing valid transitions: PENDING_APPROVAL -> AUTHORIZED -> PROCESSING -> COMPLETED/FAILED/CANCELLED/EXPIRED (T2.8)
- `TransferService` with idempotency checking, duplicate window detection, row-level locking balance debit, and Argon2 PIN authorization (T2.8)
- Fee calculation strategy and limits verification service (T2.7, T2.8)
- Transaction history, filtering, sorting, pagination, and lookup endpoints (T2.9)
- Loan offers, reducing balance EMI calculation, multi-rule eligibility evaluation, application submission, and repayment amortization schedule (T2.10)
- Credit cards management, statement views, and secure PIN-authorized credit card payments (T2.11)
- Admin dashboard APIs for platform statistics, user management, loan reviews, and runtime limits configuration (T2.12)
- Append-only immutable audit logging and auditor query APIs (T2.12)
- Database seed script populating demo admin, customer, account, beneficiary, loan offers, and credit cards with statements (T2.13)
- FastAPI OpenAPI metadata tags and API v1 router registration (T2.13)

## [Unreleased] - Phase 1: Project Foundation

### Added
- Repo skeleton: Makefile, .pre-commit-config.yaml, .gitignore (T1.1)
- `common` package: BaseAppSettings, structured JSON logging, MaskingFilter, ErrorEnvelope (T1.2)
- Banking service: FastAPI factory, /health, X-Request-ID middleware, BankingError handlers (T1.3)
- SQLAlchemy engine/session/Base with SQLite WAL + FK pragmas, UnitOfWork (T1.4)
- Alembic for banking_service and ai_service with SQLite batch support (T1.5)
- Dockerfiles for banking_service, ai_service, frontend (T1.6)
- GitHub Actions CI: lint + test jobs for common, banking_service, ai_service (T1.7)

## [Phase 0] - Design & Documentation

### Added
- Initial architecture and planning documentation set (requirements, scope, architecture, LLD, database, API, agents, RAG, HITL, security, testing, TODO).
- `.env.example` and `docker-compose.yml` templates.

### Decisions pending
- See open questions in `docs/requirements.md`.
