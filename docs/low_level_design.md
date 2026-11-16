# Low-Level Design

## 1. Repository structure
```
local-banking-ai-platform/
├── docker-compose.yml  .env.example  README.md  TODO.md  CHANGELOG.md  CONTRIBUTING.md
├── docs/
├── common/                      # logging, masking, error schema, settings base (no domain models)
├── banking_service/
│   ├── Dockerfile  alembic.ini  pyproject.toml
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py              # app factory, router mount, middleware
│   │   ├── core/                # config, security (jwt, hashing), deps, errors, rate_limit, logging
│   │   ├── db/                  # engine, session, base, unit_of_work
│   │   ├── models/              # SQLAlchemy entities
│   │   ├── schemas/             # Pydantic request/response
│   │   ├── repositories/        # one per aggregate
│   │   ├── services/            # business logic
│   │   │   ├── auth_service.py  user_service.py  account_service.py  beneficiary_service.py
│   │   │   ├── transfer_service.py  authorization_service.py  limits_service.py  fee_strategy.py
│   │   │   ├── loan_service.py  eligibility_rules.py  card_service.py  audit_service.py
│   │   ├── api/v1/              # routers: auth, users, accounts, beneficiaries, transfers,
│   │   │                        #   transactions, loans, credit_cards, admin, audit_logs
│   │   └── seed/                # simulated data
│   └── tests/{unit,integration,security}/
├── ai_service/
│   ├── Dockerfile  alembic.ini  pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                # config, auth (JWT validation), deps, errors, logging
│   │   ├── db/  models/  schemas/  repositories/
│   │   ├── api/v1/              # chat, conversations, approvals, documents, admin
│   │   ├── services/            # chat_service, conversation_service, approval_service, agent_monitor
│   │   ├── agents/
│   │   │   ├── state.py         # typed GraphState
│   │   │   ├── graph.py         # graph assembly, checkpointer
│   │   │   ├── nodes/           # supervisor, banking_ops, policy_rag, external_research, response, approval_gate
│   │   │   ├── workflows/       # beneficiary, transfer, loan, card_payment sub-graphs
│   │   │   ├── tools/           # registry.py, banking_tools.py, rag_tools.py, search_tools.py
│   │   │   ├── prompts/         # versioned prompt templates
│   │   │   └── guards/          # input_guard, output_guard (masking), injection_filter
│   │   ├── integrations/
│   │   │   ├── banking_client.py    # Adapter over HTTP
│   │   │   ├── llm_factory.py  embeddings_factory.py  vectorstore_factory.py
│   │   │   └── search/              # provider strategy
│   │   ├── rag/                 # loaders, chunkers, ingestion_pipeline, retriever, citations
│   │   └── security/            # prompt-injection defenses, doc validation
│   └── tests/{unit,integration,security,evals}/
└── frontend/
    ├── Dockerfile  app.py
    ├── pages/ (1_Chat, 2_History, 3_Documents[admin], 4_Admin[admin])
    ├── components/ (approval_card, transfer_summary, pin_dialog, citations)
    ├── clients/ (ai_client.py, banking_client.py)
    └── state/session.py
```

## 2. Banking service: layers
`api (routers) → services → repositories → models`. Routers do HTTP concerns only; services own rules and transactions via `UnitOfWork`; repositories hold queries.

### Key classes
| Class | Responsibility |
|---|---|
| `AuthService` | Register, login (Argon2 verify), issue access/refresh, rotate/revoke refresh, session list |
| `TokenService` | JWT encode/decode, `jti` denylist check |
| `AccountService` | CRUD, masking, verify (mock), ownership checks |
| `BeneficiaryService` | Create (pending verification), activate after verification+approval, modify triggers re-verification |
| `TransferService` | `prepare()`, `authorize()`, `execute()`, `cancel()`, state machine transitions |
| `AuthorizationService` | Issue challenge, verify PIN/OTP (hashed, rate-limited, lockout), mint single-use authorization bound to `summary_hash` |
| `LimitsService` | Per-txn/daily limits (Strategy per channel/user tier) |
| `FeeStrategy` | Computes charges by rail |
| `LoanService` / `EligibilityRule` set | Independent eligibility (income/EMI ratio, tenure bounds, existing loans) |
| `CardService` | Card views (tokenized/masked), bills, payments with duplicate guard |
| `AuditService` | Append-only audit events with hash chain (optional) |
| `UnitOfWork` | Session/transaction boundary |

### Transfer state machine
```
PENDING_APPROVAL --authorize--> AUTHORIZED --execute--> PROCESSING --> COMPLETED
      |                              |                        \--> FAILED
      +--cancel--> CANCELLED         +--cancel(expiry)-> CANCELLED
```
Transitions enforced in one place (`transfer_state.py`); illegal transition raises `409`.

## 3. AI service: layers
`api → services → agents/graph → tools → BankingClient`. Agents never import banking models.

### Key classes
| Class | Responsibility |
|---|---|
| `GraphState` (TypedDict) | See `agent_architecture.md` |
| `SupervisorNode` | Structured-output intent classification + route |
| `BankingOpsNode` | Tool-calling restricted to registered banking tools |
| `PolicyRagNode` | Retrieve → grounded answer with citations |
| `ExternalResearchNode` | Allow-listed search, source URLs |
| `ResponseNode` | Final composition, masking pass |
| `ApprovalGateNode` | Persists `PendingApproval`, calls `interrupt()` |
| `ToolRegistry` | Name → tool, schema, risk level (`READ`, `WRITE_LOW`, `SENSITIVE`, `FINANCIAL`), required approval flag |
| `BankingClient` | Typed HTTP adapter; retries (reads only), timeouts, error mapping, masking logs |
| `LLMFactory`, `EmbeddingsFactory`, `VectorStoreFactory` | Env-driven provider construction |
| `IngestionPipeline` | validate → extract → chunk → embed → upsert |
| `ApprovalService` | Create/expire/decide approvals; resume graph with `Command(resume=...)` |

## 4. Tool risk policy
| Risk | Examples | Policy |
|---|---|---|
| READ | balance, history, offers | Auto |
| WRITE_LOW | rename conversation, profile name | Auto, audited |
| SENSITIVE | add/modify beneficiary, password-related | Confirmation + auth |
| FINANCIAL | transfer, card payment, loan submit | Confirmation (+ auth for money) enforced by **both** graph and backend |

Tools marked SENSITIVE/FINANCIAL are only callable from the post-approval node of the workflow sub-graph; the Banking Ops agent's LLM-visible tool list only contains READ tools plus "prepare" tools (which create drafts in `PENDING_APPROVAL`, never execute).

## 5. Error handling
Banking errors map to typed `BankingError(code, http_status)`; Response agent turns them into user-safe text. No stack traces or raw payloads to the user.

## 6. Logging
JSON logs, fields: `ts, level, service, request_id, user_id_hash, event`. Masking filter redacts account/card numbers, tokens, PIN/OTP patterns.
