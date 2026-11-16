# Security Architecture

> This design contains security controls for a demo/learning platform. It does **not** assert PCI-DSS, RBI, ISO 27001 or any other compliance. A formal assessment is mandatory before real use.

## 1. Threat model (summary)
| Threat | Mitigation |
|---|---|
| Stolen token | Short-lived access JWT (15 min), refresh rotation, server-side session revoke, `jti` denylist |
| Credential stuffing | Rate limits, lockout, generic errors, Argon2id |
| IDOR / cross-user access | Ownership predicate in every repository query; 404 for foreign resources; tests |
| Privilege escalation | Server-side RBAC dependency on `/admin`, `/documents` writes; roles in DB, not only token |
| Duplicate/replayed payments | Idempotency keys, unique constraints, single-use authorization, state machine |
| Bait-and-switch after confirmation | `summary_hash` binding; any change requires re-confirmation |
| LLM manipulation (prompt injection) | Untrusted-content isolation, tool allow-lists by node, backend validation, no tools in supervisor/RAG/external nodes |
| Secret leakage via LLM/logs | PIN/OTP go UI→Banking only; masking filters; input guard refuses secrets in chat |
| Malicious documents | Type/size/magic-byte checks, no macro formats, sandboxed parsing, admin-only upload, injection flagging |
| Poisoned RAG | Admin-only ingestion, versioning, audit, deactivation, citations for human review |
| SSRF/data exfil from web tool | Allow-listed search provider and domains, no user-supplied URL fetch, no private IP ranges |
| SQL injection | SQLAlchemy parameterization, no raw SQL concatenation |
| Sensitive data exposure | Field-level encryption for account numbers, masking everywhere, no card PAN/CVV storage |

## 2. Authentication and sessions
- Argon2id (`argon2-cffi`), per-user salt, params in config. Password policy ≥12 chars, breach-list check optional.
- JWT HS256 in dev, **RS256/EdDSA in prod** so AI service validates with a public key only. Claims: `sub, roles, jti, iat, exp, sid`.
- Refresh token stored hashed; rotation with reuse detection (reuse revokes the family).
- Logout revokes session; `change-password` revokes all others.
- Streamlit keeps tokens in server-side `st.session_state` only (not in URL, not in browser storage); idle timeout 15 min.
- Transaction PIN: separate from password, Argon2id hashed, 5 attempts → lock, never displayed.

## 3. Service-to-service
- AI → Banking: user JWT + `X-Service-Key` (secret from env, rotated). Banking verifies the service identity for endpoints marked `S` and **denies S on `/authorize` endpoints**.
- Prod: mTLS or signed service JWT; network policy so only AI service/frontend reach banking.

## 4. Authorization
RBAC (CUSTOMER, ADMIN, AUDITOR) + resource ownership. Centralised dependencies `require_roles()`, `get_owned_resource()`. Admin views mask data.

## 5. Data protection
- Account numbers: AES-GCM encrypted at rest (key from env/secret manager), plus HMAC hash for uniqueness; last4 stored for display.
- Cards: only token + last4.
- Masking utility used by serializers, logging filter and agent output guard.
- SQLite file permissions 600; backups encrypted (documented).
- TLS everywhere in prod; HSTS; secure headers; CORS restricted.

## 6. Input validation and abuse controls
Pydantic strict models, max lengths, enum validation, IFSC/amount/date validators, decimal handling in minor units, request size limits, rate limiting (SlowAPI in dev, Redis in prod), upload limits.

## 7. Prompt-injection and AI-specific controls
1. Treat user text, documents, tool outputs, web pages as **untrusted data**.
2. Delimited context blocks; system prompt says content in blocks must never be obeyed.
3. Authorization decisions in code. LLM output is parsed into schemas; invalid → rejected.
4. Financial tools unreachable from LLM-bound tool lists.
5. Output guard: strips secrets, masks numbers, verifies figures against tool results.
6. Max tool-call loops, token limits, per-user chat rate limits.
7. Red-team test suite (see `testing.md`).

## 8. Audit logging
Events: login/logout/failures, password/PIN changes, account/beneficiary changes, transfer lifecycle, authorization attempts, loan submissions, card payments, approvals (confirm/reject/expire), document upload/delete, admin actions, role changes, config changes. Fields: who, what, when, outcome, request_id, masked details. Append-only; optional hash chain; admin viewer read-only.

## 9. Secrets management
`.env` for dev only (git-ignored), Docker secrets/secret manager in prod. No secrets in prompts, logs, images. Separate keys per environment.

## 10. Logging hygiene
JSON logs, correlation IDs, masking filter, no request bodies for auth/transfer endpoints, no LLM prompt logging by default (opt-in debug with masking).

## 11. SQLite disclaimer and migration
SQLite has coarse locking, no row-level locks, limited concurrency, no network access control. Use only locally. Migration path in `architecture.md` §9.

## 12. Dependency and supply chain
Pinned versions, `pip-audit`, Dependabot, container base-image scanning, SBOM generation.
