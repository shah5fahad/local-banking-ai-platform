# API Specification

Base paths: Banking `http://host:8001/api/v1`, AI `http://host:8002/api/v1`. OpenAPI at `/docs`.

## 0. Conventions
- **Auth:** `Authorization: Bearer <access JWT>` unless "Public".
- **Roles:** C = customer (own data only), A = admin, S = AI service (must also carry user JWT).
- **Error envelope** (all services):
```json
{"error":{"code":"INSUFFICIENT_BALANCE","message":"Available balance is lower than the transfer amount.","details":[{"field":"amount","issue":"..."}],"request_id":"..."}}
```
Codes: `VALIDATION_ERROR 422`, `UNAUTHENTICATED 401`, `FORBIDDEN 403`, `NOT_FOUND 404`, `CONFLICT 409`, `IDEMPOTENCY_CONFLICT 409`, `RATE_LIMITED 429`, `BUSINESS_RULE_VIOLATION 422`, `INTERNAL 500`.
- **Pagination:** `?page=1&page_size=20` (max 100) → `{"items":[],"page":1,"page_size":20,"total":0}`. **Sort:** `?sort=-created_at`.
- **Idempotency:** header `Idempotency-Key: <uuid>` required on marked endpoints; same key + same body → same response; same key + different body → 409.
- Ownership: resource IDs of other users return **404**.
- Account numbers always `XXXXXX1234`.

---
# BANKING SERVICE

## /auth
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /auth/register | Public, rate-limited | Create customer |
| POST | /auth/login | Public, rate-limited | Returns access (15 min) + refresh (7 d) |
| POST | /auth/refresh | Refresh token | Rotate refresh |
| POST | /auth/logout | C/A | Revoke current session |
| POST | /auth/logout-all | C/A | Revoke all sessions |
| GET | /auth/sessions | C/A | List active sessions |
| DELETE | /auth/sessions/{id} | C/A | Revoke one |

Register request: `{"email","phone","full_name","password"}` (password ≥12 chars, complexity; email/phone unique). 201 → `{"id","email","full_name"}`. Errors: 409 duplicate, 422.
Login request: `{"email","password"}` → `{"access_token","refresh_token","token_type":"bearer","expires_in":900}`. Lockout after 5 failures (generic error).

## /users
| GET | /users/me | C/A | Profile |
| PATCH | /users/me | C/A | Update name/phone/address (re-verify phone) |
| POST | /users/me/change-password | C/A | `{"current_password","new_password"}`; revokes other sessions |
| POST | /users/me/transaction-pin | C | Set/change PIN (requires password) |
| GET | /users/me/summary | C | Accounts overview (masked) |

## /accounts
| POST | /accounts | C | Add account `{"holder_name","account_number","ifsc","bank_name","branch_name","account_type"}` |
| GET | /accounts | C | List (filter status) |
| GET | /accounts/{id} | C | Details (masked) |
| PATCH | /accounts/{id} | C | Update non-key fields |
| DELETE | /accounts/{id} | C | Deactivate (blocked if pending txns) |
| POST | /accounts/{id}/verify | C | Start/complete verification |
| GET | /accounts/{id}/balance | C | `{"available_minor","currency","as_of"}` |

Validation: IFSC `^[A-Z]{4}0[A-Z0-9]{6}$`; account number 9-18 digits; unique per user.

## /beneficiaries
| POST | /beneficiaries | C | Creates `PENDING` beneficiary. **Requires `X-Approval-Token`** (see hitl) |
| GET | /beneficiaries | C | List, search `?q=` |
| GET | /beneficiaries/{id} | C | Details (masked) |
| PATCH | /beneficiaries/{id} | C | Modify → resets verification, requires approval token |
| DELETE | /beneficiaries/{id} | C | Deactivate |
| POST | /beneficiaries/{id}/verify | C | Mock penny-drop verification |

Beneficiary creation approval: AI/Frontend first calls `POST /approvals/beneficiary-challenges` (below) to get a challenge, user authenticates in UI, backend issues approval token bound to the payload hash.

| POST | /approvals/challenges | C | `{"action":"BENEFICIARY_CREATE","payload_hash"}` → challenge |
| POST | /approvals/challenges/{id}/verify | C | `{"pin"}` or `{"otp"}` → `{"approval_token","expires_in":300}` (single use) |

## /transfers
| POST | /transfers | C, S | **Prepare** transfer. Header `Idempotency-Key` required. Creates `PENDING_APPROVAL`. |
| GET | /transfers/{id} | C | Details |
| GET | /transfers/{id}/status | C | State only |
| POST | /transfers/{id}/authorize/challenge | C | Issues PIN/OTP challenge (method per config) |
| POST | /transfers/{id}/authorize | **C only (not S)** | `{"challenge_id","pin"|"otp"}` → state `AUTHORIZED`, returns `authorization_id`. Submitted by the UI directly. |
| POST | /transfers/{id}/execute | C, S | `{"authorization_id","summary_hash"}`; Idempotency-Key required. Executes only if AUTHORIZED, hash matches, unexpired. |
| POST | /transfers/{id}/cancel | C, S | Only `PENDING_APPROVAL`/`AUTHORIZED` |
| GET | /transfers/limits | C | Per-txn/daily limits and used amount |

Prepare request:
```json
{"source_account_id":"uuid","beneficiary_id":"uuid","amount_minor":500000,"currency":"INR","remark":"Rent","channel":"IMPS"}
```
Prepare response 201:
```json
{"id":"uuid","reference":"TXN20261109XXXX","status":"PENDING_APPROVAL",
 "beneficiary":{"name":"Rahul Sharma","account_masked":"XXXXXX4321","bank_name":"..."},
 "amount_minor":500000,"fee_minor":500,"total_debit_minor":500500,"currency":"INR",
 "available_balance_after_minor":1234500,"summary_hash":"sha256:...","expires_at":"..."}
```
Errors: `INSUFFICIENT_BALANCE`, `LIMIT_EXCEEDED`, `BENEFICIARY_NOT_VERIFIED`, `DUPLICATE_TRANSACTION` (same beneficiary+amount within 2 min window w/o new key → 409 with hint), `INVALID_STATE_TRANSITION`, `AUTHORIZATION_INVALID`, `AUTHORIZATION_EXPIRED`, `SUMMARY_MISMATCH`.
Business logic: validate ownership/active/verified → balance (incl. fee) → limits → duplicate window → compute `summary_hash` over {txn id, user, source, beneficiary, amount, fee, currency}.

## /transactions
| GET | /transactions | C | Filters: `from`, `to`, `type`, `min_amount`, `max_amount`, `status`, `beneficiary_id`, `reference`; pagination/sort |
| GET | /transactions/{id} | C | Details |
| GET | /transactions/by-reference/{ref} | C | Lookup |

## /loans
| GET | /loans/offers | C | Pre-approved offers |
| GET | /loans/offers/{id} | C | Details |
| POST | /loans/eligibility | C | `{"loan_type","amount_minor","tenure_months","monthly_income_minor"}` → `{"eligible":bool,"max_amount_minor","reasons":[]}` |
| POST | /loans/applications | C, S | Submit. Idempotency-Key required. Requires `confirmation_id` (user confirmation record) |
| GET | /loans/applications | C | History |
| GET | /loans/applications/{id} | C | Status |
| GET | /loans/active | C | Active loans |
| GET | /loans/{id}/repayment | C | Schedule/EMI details |

## /credit-cards
| GET | /credit-cards | C | Masked list |
| GET | /credit-cards/{id} | C | Details (last4, limit) |
| GET | /credit-cards/{id}/outstanding | C | Outstanding balance |
| GET | /credit-cards/{id}/statements | C | Statements (paginated) |
| GET | /credit-cards/{id}/bills/current | C | Current bill |
| POST | /credit-cards/{id}/payments | C, S | Prepare payment `PENDING_APPROVAL`; idempotency required |
| POST | /credit-cards/payments/{id}/authorize | C only | PIN/OTP |
| POST | /credit-cards/payments/{id}/execute | C, S | After authorization |
| GET | /credit-cards/{id}/payments | C | History |
| GET | /credit-cards/payments/{id}/status | C | Status |

## /admin  (A only, server-enforced)
GET /admin/stats · GET /admin/users · PATCH /admin/users/{id}/status · PUT /admin/users/{id}/roles · GET /admin/transactions · GET /admin/loan-applications · GET /admin/config · PATCH /admin/config (limits, expiry values). All masked; all audited.

## /audit-logs  (A, AUDITOR)
GET /audit-logs?actor=&action=&from=&to=&resource_type=&outcome= · GET /audit-logs/{id}

---
# AI CHAT SERVICE

JWT is validated locally (public key/JWKS from banking). The AI service stores no passwords and never mints tokens.

## /chat
| POST | /chat/messages | C | `{"conversation_id"?,"message"}` → SSE stream of events: `status`, `tool`, `token`, `approval_required`, `citations`, `done`, `error` |
| POST | /chat/approvals/{approval_id}/decision | C | `{"decision":"CONFIRM"|"REJECT"}` resumes/cancels graph. Not a chat message, so the LLM cannot confirm. |
| POST | /chat/approvals/{approval_id}/resume | C | After the UI completed PIN/OTP directly at banking; body has no secret: `{"authorization_id"}` |
| GET | /chat/approvals/{approval_id} | C | Current approval state + masked summary |

`approval_required` event payload:
```json
{"approval_id":"uuid","workflow":"TRANSFER","stage":"CONFIRM","summary":{"beneficiary":"Rahul Sharma","account_masked":"XXXXXX4321","amount":"₹5,000.00","charges":"₹5.00","total_debit":"₹5,005.00"},"summary_hash":"sha256:...","expires_at":"..."}
```

## /conversations
GET /conversations?q=&page= · POST /conversations · GET /conversations/{id} (messages with timestamps) · PATCH /conversations/{id} (rename) · DELETE /conversations/{id} (soft delete). Always filtered by owner.

## /documents  (A for writes)
| POST | /documents | A | multipart upload: file, category, version, name. Returns 202 + `status=PROCESSING` |
| GET | /documents | A | List/filter |
| GET | /documents/{id} | A | Metadata + processing status |
| POST | /documents/{id}/reprocess | A | Re-run pipeline |
| POST | /documents/{id}/deactivate and /activate | A | Toggle retrieval eligibility |
| DELETE | /documents/{id} | A | Delete doc, chunks, vectors |
| GET | /documents/{id}/versions | A | Versions |

## /admin (AI)
GET /admin/conversations (masked) · GET /admin/agent-executions?conversation_id=&status= · GET /admin/ai-stats · GET/PATCH /admin/ai-config (non-secret config: model name, top-k, thresholds).

## Rate limits (default)
Auth: 5/min/IP login. Chat: 20 msgs/min/user. PIN/OTP verify: 5 attempts then lock. Uploads: 10/hour/admin.
