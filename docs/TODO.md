# TODO: Phased Task Breakdown

Legend: **D** = depends on, **AC** = acceptance criteria. Each task includes tests and doc updates.

## Phase 0: Design review (current)
- [ ] T0.1 Review docs and resolve open questions (`docs/requirements.md` §5). AC: decisions recorded in `CHANGELOG.md`.

## Phase 1: Project Foundation
- [x] T1.1 Repo skeleton, `pyproject.toml` per service, ruff/mypy/pre-commit. AC: `make lint test` runs.
- [x] T1.2 `common` package: settings base, JSON logging, masking filter, error envelope. D: T1.1. AC: unit tests for masking.
- [x] T1.3 Banking service app factory, health endpoint, config, request-id middleware. D: T1.2.
- [x] T1.4 SQLAlchemy engine/session/Base, SQLite pragmas (FK, WAL), UnitOfWork. D: T1.3.
- [x] T1.5 Alembic setup for banking and AI DBs. AC: `upgrade head` and `downgrade base` pass in CI.
- [x] T1.6 Docker/Compose (banking, ai, frontend, volumes), `.env.example` wiring. AC: `docker compose up` healthy.
- [x] T1.7 CI pipeline.

## Phase 2: Banking APIs
- [x] T2.1 Models + migrations: user, role, session, audit_log. D: T1.5.
- [x] T2.2 AuthService, TokenService, Argon2, login lockout, refresh rotation, logout/revoke, sessions API. AC: security tests for auth pass.
- [x] T2.3 RBAC dependencies, ownership helpers, audit service. D: T2.2.
- [x] T2.4 User APIs (profile, change password, PIN). 
- [x] T2.5 Accounts: encryption, masking, CRUD, verify, balance. 
- [x] T2.6 Beneficiaries + approval challenge/token service. D: T2.5.
- [x] T2.7 Limits + fee strategies. 
- [x] T2.8 Transfer state machine, prepare, authorize, execute, cancel, idempotency, summary_hash. D: T2.6, T2.7. AC: concurrency and replay tests.
- [x] T2.9 Transactions listing/filter/pagination. 
- [x] T2.10 Loans: offers, eligibility rules, applications, repayment. 
- [x] T2.11 Credit cards: views, statements, payments (reuse authorization). D: T2.8.
- [x] T2.12 Admin + audit-log APIs. 
- [x] T2.13 Seed data + OpenAPI polish. AC: Swagger documents all endpoints with examples.

## Phase 3: AI Infrastructure
- [x] T3.1 AI service skeleton, JWT validation (JWKS/public key), AI DB models/migrations. D: T1.5.
- [x] T3.2 LLMFactory, EmbeddingsFactory, VectorStoreFactory (env-driven; fake providers for tests).
- [x] T3.3 `BankingClient` adapter (typed, timeouts, error mapping, masking, token injection). D: T2.x endpoints. AC: contract tests against banking test app.
- [x] T3.4 GraphState, graph assembly, SQLite checkpointer, request-scoped token context. AC: token absent from checkpoint rows.
- [x] T3.5 Tool registry with risk levels and `allowed_nodes`.
- [x] T3.6 input_guard / output_guard / injection heuristics.
- [x] T3.7 Supervisor node + routing table + deterministic overlay. D: T3.4.

## Phase 4: Banking AI Agents
- [x] T4.1 Banking Ops node with READ tools (accounts, balance, transactions, offers, cards).
- [x] T4.2 Document ingestion pipeline (validate, extract, chunk, embed, store) + document APIs. D: T3.2.
- [x] T4.3 Policy RAG node with citations and abstain behaviour. D: T4.2.
- [x] T4.4 External Research node (search strategy, allow-list, labelling).
- [x] T4.5 Response node + formatter + masking. 
- [x] T4.6 Conversation/message persistence, SSE streaming chat API, agent_execution logging.
- [x] T4.7 Unsupported / out-of-domain handling. AC: spec routing table passes 100%.

## Phase 5: Human-in-the-Loop
- [x] T5.1 PendingApproval model/service, approval_gate with `interrupt()`, decision/resume APIs. D: T3.4.
- [x] T5.2 Beneficiary workflow (draft/confirm/authenticate/create). D: T2.6.
- [x] T5.3 Transfer workflow (prepare → confirm → auth direct to banking → resume → execute → status). D: T2.8.
- [x] T5.4 Loan workflow. D: T2.10.
- [x] T5.5 Card payment workflow. D: T2.11.
- [x] T5.6 Expiry sweeper, cleanup, checkpoint pruning, superseding rules.
- [x] T5.7 HITL security tests (no write before approval, tamper, replay, cross-user).

## Phase 6: Frontend
- [x] T6.1 Auth pages, session handling, route guards, idle timeout.
- [x] T6.2 Chat page: streaming, tool status, approval card, PIN dialog posting directly to banking, citations.
- [x] T6.3 Chat history (list/search/rename/delete).
- [x] T6.4 Admin: documents UI (upload, status, reprocess, deactivate, delete, versions).
- [x] T6.5 Admin dashboard: stats, users/roles, transactions, loans, masked chat monitor, audit viewer, agent executions, config.
- [x] T6.6 Optional direct banking screens (accounts, beneficiaries, history).

## Phase 7: Banking System Improvements
- [x] T7.1 Auto-create bank account on signup: enhance user signup (`banking_service/app/api/v1/auth.py` and `AuthService`) to trigger automatic creation and linking of a verified primary bank account upon successful user registration with necessary validations. D: T2.2, T2.5. AC: new user registration automatically creates an initial active bank account; unit and integration tests verify creation flow.
- [x] T7.2 Auto-generate card details on signup: update signup logic to automatically generate secure card details (card number, expiration date, and CVV) and store them securely in the database. D: T2.11, T7.1. AC: new user registration automatically provisions an active card securely linked to user; tests pass.
- [x] T7.3 Provision initial loan offers on signup: automatically create at least three loan offers (home loan, car loan, personal loan) with defined terms, conditions, and interest rates linked to the user account in the database upon registration. D: T2.10, T7.1. AC: newly registered user has at least 3 distinct loan offers accessible via loans API; tests verify offer generation.
- [x] T7.4 Customer dashboard details display: update dashboard endpoint and frontend view to fetch and display bank account, card, and loan details to the user on their dashboard after logging in. D: T6.1, T6.6, T7.1, T7.2, T7.3. AC: authenticated user dashboard displays accounts, card details, and loan offers seamlessly post-login.

## Phase 8: Testing and Hardening
- [ ] T8.1 Unit/integration suites to coverage targets.
- [ ] T8.2 Security suite (`testing.md` §2).
- [ ] T8.3 AI eval datasets and runner.
- [ ] T8.4 Performance/concurrency tests; fix hot spots.
- [ ] T8.5 Error-handling and UX pass; log secret-leak audit.

## Phase 9: Deployment and Documentation
- [ ] T9.1 Production-like Compose profile (TLS reverse proxy, non-root containers, healthchecks).
- [ ] T9.2 Final docs: API docs export, deployment guide, troubleshooting, PostgreSQL migration guide.
- [ ] T9.3 Release checklist and CHANGELOG 0.1.0.

## Suggested order for incremental delivery
Foundation → Auth → Accounts/Beneficiaries → Transfers → (parallel) Loans/Cards and AI infra → Agents → HITL → Frontend → Banking System Improvements → Hardening.
