# Contributing

## Ground rules (non-negotiable)
1. The AI service must never import banking models/repositories or touch the banking DB. Banking access = `BankingClient` over HTTP only.
2. No secret (password, PIN, OTP, token, full account/card number) in prompts, graph state, logs, vector DB, or tests fixtures.
3. LLM output is never an authorization. Sensitive actions are validated by the banking backend.
4. Do not claim regulatory compliance.
5. SQLite is dev-only.

## Workflow
- Branches: `feature/<id>-short-name`; PRs small and linked to a TODO task.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Each PR: tests, docs updated, CHANGELOG entry, migration if schema changes.

## Code standards
- Python 3.11+, full type hints, `mypy --strict` on services, `ruff` + `ruff format`.
- Layers: router → service → repository. No business logic in routers; no HTTP in repositories.
- Money in integer minor units; UTC timestamps.
- Docstrings on public classes/functions; comments explain why.
- Use dependency injection (`Depends`); avoid globals.
- Avoid unnecessary abstractions: add a pattern only when a second implementation or test seam exists.

## Testing
`pytest -q`; markers: `unit`, `integration`, `security`, `eval`, `live_llm`. New endpoints need happy path, validation, authz, and ownership tests.

## Database changes
Create Alembic migration per DB (`alembic revision --autogenerate`), review manually, test upgrade and downgrade.

## Prompts
Prompts live in `agents/prompts/` with version ids; changes require eval run results in PR.

## Security review checklist (PR template)
- [ ] New endpoint has auth, role, ownership check
- [ ] Inputs validated; errors use envelope
- [ ] Sensitive fields masked in responses/logs
- [ ] Audit event emitted for sensitive actions
- [ ] No new secret in logs/prompts
